#!/usr/bin/env python3
"""G4A/G4B Live READ-ONLY probe — Accurate upstream via existing AccurateClient.

Does NOT call undeployed gateway routes (/sales-invoices, /delivery-notes list).
Uses AccurateClient._request only (available on VPS-deployed client).

Env (required):
  GATEWAY_MODE=live
  ACCURATE_API_TOKEN
  ACCURATE_SIGNATURE_SECRET
Optional:
  ACCURATE_DATABASE_ID
  G4_PROBE_PAGE_SIZE (default 5)
  G4_PROBE_MAX_PAGES (default 2)  — hard cap; never full census
  G4_PROBE_SJ_DETAIL_ID (default 120055) — optional detail.do smoke

Sanitized stdout only: HTTP status, key names, counts, id hashes.
Never prints customer names, phones, amounts, tokens, or document numbers in full.
Exit 2 = missing creds / wrong mode. Exit 1 = upstream failure. Exit 0 = probe ran.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "accurate-gateway"))

from app.accurate_client import AccurateClient, AccurateUpstreamError  # noqa: E402
from app.config import GatewaySettings, get_settings  # noqa: E402


def _h(value: Any) -> str | None:
    s = str(value or "").strip()
    if not s:
        return None
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def _keys(obj: Any, *, limit: int = 40) -> list[str]:
    if not isinstance(obj, dict):
        return []
    return sorted(str(k) for k in obj.keys())[:limit]


def _extract_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = data.get("d") or data.get("data") or []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _extract_total(data: dict[str, Any]) -> int | None:
    sp = data.get("sp") if isinstance(data.get("sp"), dict) else {}
    for key in ("rowCount", "rowTotal", "totalRows", "totalRow"):
        val = sp.get(key)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass
    for key in ("rowCount", "total", "totalRows"):
        val = data.get(key)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass
    return None


def _owing_keys_present(row: dict[str, Any]) -> dict[str, bool]:
    return {
        "primeOwing": "primeOwing" in row and row.get("primeOwing") is not None,
        "owingAmount": "owingAmount" in row and row.get("owingAmount") is not None,
        "owing": "owing" in row and row.get("owing") is not None,
        "outstandingAmount": "outstandingAmount" in row
        and row.get("outstandingAmount") is not None,
        "id": row.get("id") is not None,
        "number_present": bool(str(row.get("number") or row.get("no") or "").strip()),
        "totalAmount_present": row.get("totalAmount") is not None,
    }


def _reconcile(id_hashes: list[str], claimed_total: int | None) -> dict[str, Any]:
    unique = set(id_hashes)
    dup = len(id_hashes) - len(unique)
    return {
        "sampled_row_count": len(id_hashes),
        "unique_ids": len(unique),
        "duplicate_ids": dup,
        "claimed_total": claimed_total,
        "sample_matches_claimed": (
            claimed_total is not None
            and len(unique) == int(claimed_total)
            and dup == 0
        ),
        "full_universe_verified": False,
        "note": "Sample pages only — never claim full Accurate census from this probe",
    }


async def _get_raw(
    client: AccurateClient, path: str, params: dict[str, Any]
) -> tuple[int, dict[str, Any] | None, str | None]:
    """Return (http_status_or_mapped, body, error_code)."""
    try:
        body = await client._request("GET", path, params=params)
        return 200, body if isinstance(body, dict) else None, None
    except AccurateUpstreamError as exc:
        # Client maps non-2xx; surface status when encoded in message.
        status = int(exc.status_code or 502)
        return status, None, exc.code


async def main() -> int:
    get_settings.cache_clear()
    mode = (os.environ.get("GATEWAY_MODE") or "").strip().lower()
    page_size = max(1, min(int(os.environ.get("G4_PROBE_PAGE_SIZE") or 5), 20))
    max_pages = max(1, min(int(os.environ.get("G4_PROBE_MAX_PAGES") or 2), 5))
    sj_detail_id = (os.environ.get("G4_PROBE_SJ_DETAIL_ID") or "120055").strip()

    report: dict[str, Any] = {
        "probe": "g4ab_live_readonly",
        "write_attempted": False,
        "deploy_required": False,
        "gateway_list_routes_used": False,
        "page_size": page_size,
        "max_pages": max_pages,
        "g4a": {"verdict": "BLOCKED"},
        "g4b": {"verdict": "BLOCKED"},
        "live_verified": False,
    }

    if mode != "live":
        report["blocker"] = "GATEWAY_MODE must be live"
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2

    settings = GatewaySettings()
    client = AccurateClient(settings)
    if not client.configured():
        report["blocker"] = (
            "ACCURATE_API_TOKEN and ACCURATE_SIGNATURE_SECRET not injected "
            "in this environment (VPS has them; agent VM does not)"
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2

    # --- G4A sales-invoice/list.do ---
    inv_ids: list[str] = []
    inv_key_union: set[str] = set()
    inv_owing_flags = {
        "primeOwing": 0,
        "owingAmount": 0,
        "owing": 0,
        "outstandingAmount": 0,
        "id": 0,
        "rows_seen": 0,
    }
    inv_claimed: int | None = None
    inv_pages: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        status, body, err = await _get_raw(
            client,
            "/accurate/api/sales-invoice/list.do",
            {
                "fields": (
                    "id,number,statusName,status,transDate,totalAmount,"
                    "primeOwing,owingAmount,owing"
                ),
                "sp.page": page,
                "sp.pageSize": page_size,
            },
        )
        page_ev = {
            "page": page,
            "http_status": status,
            "error_code": err,
            "row_count": 0,
            "response_top_keys": _keys(body) if body else [],
        }
        if body:
            rows = _extract_rows(body)
            page_ev["row_count"] = len(rows)
            page_ev["sp_keys"] = _keys(body.get("sp") if isinstance(body.get("sp"), dict) else {})
            claimed = _extract_total(body)
            if claimed is not None:
                inv_claimed = claimed
            for row in rows:
                inv_owing_flags["rows_seen"] += 1
                flags = _owing_keys_present(row)
                for k in ("primeOwing", "owingAmount", "owing", "outstandingAmount", "id"):
                    if flags.get(k):
                        inv_owing_flags[k] += 1
                inv_key_union.update(_keys(row))
                if row.get("id") is not None:
                    inv_ids.append(_h(row.get("id")) or "")
            if not rows:
                inv_pages.append(page_ev)
                break
        inv_pages.append(page_ev)
        if status != 200:
            break

    report["g4a"] = {
        "endpoint": "/accurate/api/sales-invoice/list.do",
        "pages": inv_pages,
        "proven_row_keys": sorted(inv_key_union),
        "owing_field_hits": inv_owing_flags,
        "claimed_total": inv_claimed,
        "reconciliation": _reconcile([x for x in inv_ids if x], inv_claimed),
        "verdict": (
            "LIVE_PARTIAL"
            if inv_pages and inv_pages[0].get("http_status") == 200
            else "BLOCKED"
        ),
    }

    # Optional: one invoice detail if list returned an id (hash only; re-fetch first page id raw via second call)
    # Skip detail if list failed — avoid inventing ids.
    if inv_pages and inv_pages[0].get("http_status") == 200 and inv_owing_flags["id"] > 0:
        # Re-fetch page 1 to get a real numeric id for detail (not printed).
        st, body, err = await _get_raw(
            client,
            "/accurate/api/sales-invoice/list.do",
            {
                "fields": "id,primeOwing,owingAmount,owing,totalAmount",
                "sp.page": 1,
                "sp.pageSize": 1,
            },
        )
        detail_ev: dict[str, Any] = {"http_status": st, "error_code": err}
        if body:
            rows = _extract_rows(body)
            if rows and rows[0].get("id") is not None:
                iid = rows[0]["id"]
                dst, dbody, derr = await _get_raw(
                    client,
                    "/accurate/api/sales-invoice/detail.do",
                    {"id": int(iid) if str(iid).isdigit() else iid},
                )
                detail_ev = {
                    "http_status": dst,
                    "error_code": derr,
                    "id_hash": _h(iid),
                    "detail_keys": _keys(dbody.get("d") if isinstance(dbody, dict) and isinstance(dbody.get("d"), dict) else dbody),
                    "owing_flags": _owing_keys_present(
                        dbody.get("d")  # type: ignore[arg-type]
                        if isinstance(dbody, dict) and isinstance(dbody.get("d"), dict)
                        else (dbody if isinstance(dbody, dict) else {})
                    )
                    if dst == 200
                    else None,
                }
        report["g4a"]["detail_sample"] = detail_ev

    # --- G4B delivery-order/list.do ---
    sj_ids: list[str] = []
    sj_key_union: set[str] = set()
    sj_claimed: int | None = None
    sj_pages: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        status, body, err = await _get_raw(
            client,
            "/accurate/api/delivery-order/list.do",
            {
                "fields": "id,number,statusName,status,shipDate,transDate",
                "sp.page": page,
                "sp.pageSize": page_size,
            },
        )
        page_ev = {
            "page": page,
            "http_status": status,
            "error_code": err,
            "row_count": 0,
            "response_top_keys": _keys(body) if body else [],
        }
        if body:
            rows = _extract_rows(body)
            page_ev["row_count"] = len(rows)
            page_ev["sp_keys"] = _keys(body.get("sp") if isinstance(body.get("sp"), dict) else {})
            claimed = _extract_total(body)
            if claimed is not None:
                sj_claimed = claimed
            for row in rows:
                sj_key_union.update(_keys(row))
                if row.get("id") is not None:
                    sj_ids.append(_h(row.get("id")) or "")
            if not rows:
                sj_pages.append(page_ev)
                break
        sj_pages.append(page_ev)
        if status != 200:
            break

    # Known detail smoke (Owner-proven 120055) — id only, no PII
    detail_status, detail_body, detail_err = await _get_raw(
        client,
        "/accurate/api/delivery-order/detail.do",
        {"id": int(sj_detail_id) if sj_detail_id.isdigit() else sj_detail_id},
    )
    detail_row = None
    if isinstance(detail_body, dict):
        detail_row = (
            detail_body.get("d")
            if isinstance(detail_body.get("d"), dict)
            else detail_body
        )

    report["g4b"] = {
        "endpoint": "/accurate/api/delivery-order/list.do",
        "pages": sj_pages,
        "proven_row_keys": sorted(sj_key_union),
        "claimed_total": sj_claimed,
        "reconciliation": _reconcile([x for x in sj_ids if x], sj_claimed),
        "detail_smoke": {
            "endpoint": f"/accurate/api/delivery-order/detail.do?id={sj_detail_id}",
            "http_status": detail_status,
            "error_code": detail_err,
            "id_hash": _h(sj_detail_id),
            "detail_keys": _keys(detail_row) if isinstance(detail_row, dict) else [],
        },
        "verdict": (
            "LIVE_PARTIAL"
            if sj_pages and sj_pages[0].get("http_status") == 200
            else "BLOCKED"
        ),
    }

    report["live_verified"] = (
        report["g4a"]["verdict"] == "LIVE_PARTIAL"
        and report["g4b"]["verdict"] == "LIVE_PARTIAL"
    )
    # Full Ready never from this capped sample.
    if report["live_verified"]:
        report["g4a"]["verdict"] = "LIVE_PARTIAL_NOT_FULL_COVERAGE"
        report["g4b"]["verdict"] = "LIVE_PARTIAL_NOT_FULL_COVERAGE"

    print(json.dumps(report, indent=2, sort_keys=True))
    if report["g4a"]["verdict"].startswith("BLOCKED") or report["g4b"][
        "verdict"
    ].startswith("BLOCKED"):
        return 1 if client.configured() else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
