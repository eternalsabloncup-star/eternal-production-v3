#!/usr/bin/env python3
"""Phase 5 live Accurate probe — NEVER uses fixtures.

Requires:
  GATEWAY_MODE=live
  ACCURATE_API_TOKEN
  ACCURATE_SIGNATURE_SECRET
  (optional) ACCURATE_DATABASE_ID pin after api-token.do
  GATEWAY_M2M_TOKEN (for optional local gateway hop)

Writes sanitized evidence only (no customer names, no tokens).
Exit 2 if credentials missing. Exit 1 on live failure.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "accurate-gateway"))

from app.accurate_client import AccurateClient, AccurateUpstreamError  # noqa: E402
from app.config import GatewaySettings, get_settings  # noqa: E402


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _sanitize_so(row: dict) -> dict:
    number = str(row.get("number") or "")
    lines = row.get("line_items") or []
    return {
        "so_hash": _hash(number) if number else None,
        "so_suffix": number[-4:] if len(number) >= 4 else None,
        "status": row.get("status"),
        "branch_id": (row.get("branch") or {}).get("id")
        if isinstance(row.get("branch"), dict)
        else row.get("branch_id"),
        "line_count": len(lines) if isinstance(lines, list) else 0,
        "qty_sum": sum(float(li.get("qty") or 0) for li in lines)
        if isinstance(lines, list)
        else None,
        "live_verified": True,
    }


def _sanitize_receipt(row: dict) -> dict:
    rid = str(row.get("id") or row.get("number") or "")
    return {
        "receipt_hash": _hash(rid) if rid else None,
        "status": row.get("status"),
        "cancelled": row.get("cancelled"),
        "reversed": row.get("reversed"),
        "verifiable": row.get("verifiable"),
        "so_suffix": str(row.get("sales_order_number") or "")[-4:] or None,
        "amount_present": row.get("amount") is not None,
        "live_verified": True,
    }


def _sanitize_sj(row: dict) -> dict:
    sid = str(row.get("id") or row.get("number") or "")
    lines = row.get("line_items") or []
    return {
        "sj_hash": _hash(sid) if sid else None,
        "status": row.get("status"),
        "cancelled": row.get("cancelled"),
        "verifiable": row.get("verifiable"),
        "so_suffix": str(row.get("sales_order_number") or "")[-4:] or None,
        "line_count": len(lines) if isinstance(lines, list) else 0,
        "qty_sum": sum(float(li.get("qty") or 0) for li in lines)
        if isinstance(lines, list)
        else None,
        "live_verified": True,
    }


async def main() -> int:
    get_settings.cache_clear()
    mode = (os.environ.get("GATEWAY_MODE") or "").strip().lower()
    if mode != "live":
        print(
            json.dumps(
                {
                    "ok": False,
                    "blocker": "GATEWAY_MODE must be live (fixture forbidden for Phase 5)",
                    "live_verified": False,
                }
            )
        )
        return 2
    settings = GatewaySettings()
    client = AccurateClient(settings)
    if not client.configured():
        print(
            json.dumps(
                {
                    "ok": False,
                    "blocker": (
                        "ACCURATE_API_TOKEN and ACCURATE_SIGNATURE_SECRET required"
                    ),
                    "live_verified": False,
                }
            )
        )
        return 2

    evidence: dict = {
        "mode": "live",
        "live_verified": False,
        "open_db": None,
        "so_list": None,
        "so_detail": None,
        "receipt": None,
        "delivery_note": None,
        "reject_checks": {},
        "write_attempted": False,
    }
    out_path = Path(os.environ.get("PHASE5_EVIDENCE_PATH", "/tmp/epv3-p5-live-evidence.json"))

    try:
        listed = await client.list_sales_orders(limit=5)
        evidence["so_list"] = {
            "count_returned": len(listed),
            "sample": [_sanitize_so(r) for r in listed[:3]],
        }
        if not listed:
            evidence["blocker"] = "Accurate returned empty sales-order list"
            out_path.write_text(json.dumps(evidence, indent=2))
            print(json.dumps({"ok": False, **evidence}, indent=2))
            return 1

        target_number = str(listed[0].get("number") or "")
        detail = await client.get_sales_order(target_number)
        evidence["so_detail"] = _sanitize_so(detail)
        evidence["open_db"] = {"ok": True}

        # Optional document probes via env (Owner supplies ids — never invent)
        receipt_id = (os.environ.get("PHASE5_LIVE_RECEIPT_ID") or "").strip()
        sj_id = (os.environ.get("PHASE5_LIVE_SJ_ID") or "").strip()
        cancel_receipt = (os.environ.get("PHASE5_LIVE_CANCELLED_RECEIPT_ID") or "").strip()
        cancel_sj = (os.environ.get("PHASE5_LIVE_CANCELLED_SJ_ID") or "").strip()

        if receipt_id:
            evidence["receipt"] = _sanitize_receipt(await client.get_receipt(receipt_id))
        else:
            evidence["receipt"] = {"skipped": True, "reason": "PHASE5_LIVE_RECEIPT_ID unset"}

        if sj_id:
            evidence["delivery_note"] = _sanitize_sj(await client.get_delivery_note(sj_id))
        else:
            evidence["delivery_note"] = {
                "skipped": True,
                "reason": "PHASE5_LIVE_SJ_ID unset",
            }

        if cancel_receipt:
            row = await client.get_receipt(cancel_receipt)
            evidence["reject_checks"]["cancelled_receipt"] = {
                "cancelled": row.get("cancelled"),
                "reversed": row.get("reversed"),
                "verifiable": row.get("verifiable"),
                "status": row.get("status"),
                "would_reject": bool(
                    row.get("cancelled")
                    or row.get("reversed")
                    or row.get("verifiable") is False
                ),
            }
        if cancel_sj:
            row = await client.get_delivery_note(cancel_sj)
            evidence["reject_checks"]["cancelled_sj"] = {
                "cancelled": row.get("cancelled"),
                "verifiable": row.get("verifiable"),
                "status": row.get("status"),
                "would_reject": bool(
                    row.get("cancelled") or row.get("verifiable") is False
                ),
            }

        evidence["live_verified"] = True
        evidence["ok"] = True
        out_path.write_text(json.dumps(evidence, indent=2))
        print(json.dumps({"ok": True, "evidence_path": str(out_path), **evidence}, indent=2))
        return 0
    except AccurateUpstreamError as exc:
        evidence["ok"] = False
        evidence["error"] = {"code": exc.code, "message": exc.message}
        out_path.write_text(json.dumps(evidence, indent=2))
        print(json.dumps(evidence, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
