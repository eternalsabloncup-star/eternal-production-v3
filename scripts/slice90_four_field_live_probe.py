#!/usr/bin/env python3
"""Step 90 — sanitized four-field Accurate Live evidence probe.

Scope only:
  1) Sales / Penjual
  2) Ekspedisi / Pengiriman
  3) Status Pesanan (Owner H CF4)
  4) Buffer / Non-Buffer (Owner H CF5)

Safety:
  - GET sales-order list/detail only; POST api-token.do auth bootstrap only.
  - Never print credentials, tokens, customer data, SO numbers, raw payloads,
    or field values — only JSON path names + MATCH/MISMATCH/UNKNOWN.
  - Does not invent new mappings; path discovery for Pengiriman candidates is
    presence-only until Live proves which key maps to UI Pengiriman.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "accurate-gateway"))

DEFAULT_ENV_FILE = "/etc/epv3/gateway.env"
PROBE_NAME = "slice90_four_field_live_probe"

# Proven salesman keys already used by gateway normalizer.
_SALES_KEYS = (
    "salesmanList",
    "salesPersonList",
    "salespersonList",
    "salesList",
    "salesPerson",
    "salesperson",
    "salesman",
    "sales",
    "salesPersonName",
    "salespersonName",
    "salesmanName",
    "salesName",
)

# Keys already mapped to expedition by gateway (native/label).
_EXPEDITION_MAPPED_KEYS = (
    "expedition",
    "expeditionName",
    "courier",
    "courierName",
    "shippingInfo",
    "shippingMethod",
    "shippingMethodName",
    "deliveryMethod",
)

# Unproven Pengiriman UI candidates — report presence only; never auto-map.
_PENGIRIMAN_CANDIDATE_KEYS = (
    "shipment",
    "shipmentName",
    "shipVia",
    "shipViaName",
    "shipping",
    "shippingName",
    "pengiriman",
    "pengirimanName",
)


def _load_slice1l():
    path = ROOT / "scripts" / "slice1l_single_po_field_probe.py"
    spec = importlib.util.spec_from_file_location("slice1l_probe", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _so_hash(number: str) -> str:
    return hashlib.sha256(number.encode("utf-8")).hexdigest()[:12]


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_present(v) for v in value.values())
    if isinstance(value, list):
        return any(_present(v) for v in value)
    return True


def _entity_sales_paths(entity: dict[str, Any], prefix: str) -> list[str]:
    found: list[str] = []
    for key in _SALES_KEYS:
        if key not in entity:
            continue
        if _present(entity.get(key)):
            found.append(f"{prefix}.{key}" if prefix else key)
    return found


def discover_sales_paths(raw: dict[str, Any]) -> list[str]:
    paths = _entity_sales_paths(raw, "")
    lines = raw.get("detailItem") or raw.get("detailItems") or raw.get("items") or []
    if not isinstance(lines, list):
        return paths
    line_keys: set[str] = set()
    for line in lines:
        if not isinstance(line, dict):
            continue
        for key in _SALES_KEYS:
            if key in line and _present(line.get(key)):
                line_keys.add(f"detailItem[].{key}")
    paths.extend(sorted(line_keys))
    # Stable unique
    return list(dict.fromkeys(paths))


def discover_pengiriman_paths(raw: dict[str, Any]) -> dict[str, Any]:
    mapped_present: list[str] = []
    candidate_present: list[str] = []
    for key in _EXPEDITION_MAPPED_KEYS:
        if key in raw and _present(raw.get(key)):
            mapped_present.append(key)
    for key in _PENGIRIMAN_CANDIDATE_KEYS:
        if key in raw and _present(raw.get(key)):
            candidate_present.append(key)
    return {
        "mapped_native_paths_present": mapped_present,
        "unproven_candidate_paths_present": candidate_present,
        "proven_json_path": mapped_present[0] if mapped_present else "UNKNOWN",
    }


def cf_slot_presence(raw: dict[str, Any], index: int) -> dict[str, str]:
    value_keys = (f"charField{index}", f"customField{index}", f"dataClassification{index}")
    label_keys = (
        f"charField{index}Name",
        f"charField{index}Label",
        f"charField{index}Title",
    )
    value_present = any(k in raw and _present(raw.get(k)) for k in value_keys)
    label_present = any(k in raw and _present(raw.get(k)) for k in label_keys)
    path = f"charField{index}" if f"charField{index}" in raw else "UNKNOWN"
    if value_present and f"charField{index}" not in raw:
        for k in value_keys:
            if k in raw and _present(raw.get(k)):
                path = k
                break
    return {
        "json_path": path if value_present or label_present else "UNKNOWN",
        "value_present": "true" if value_present else "false",
        "companion_label_present": "true" if label_present else "false",
    }


def classify_urgent(mapped_state: Any) -> str:
    if mapped_state == "normal":
        return "normal"
    if mapped_state in {"approved_urgent", "legacy_urgent"}:
        return "urgent"
    return "unknown"


def classify_buffer(mapped_bool: Any) -> str:
    if mapped_bool is True:
        return "buffer"
    if mapped_bool is False:
        return "non_buffer"
    return "unknown"


def cmp_str(actual: Any, expected: str) -> str:
    if actual is None or (isinstance(actual, str) and not str(actual).strip()):
        return "UNKNOWN"
    if str(actual).strip().lower() == str(expected).strip().lower():
        return "MATCH"
    return "MISMATCH"


def cmp_bool(actual: Any, expected: bool) -> str:
    if actual is None:
        return "UNKNOWN"
    if isinstance(actual, bool):
        return "MATCH" if actual is expected else "MISMATCH"
    return "UNKNOWN"


def build_four_field_report(
    raw: dict[str, Any],
    expected: dict[str, Any],
    so_number: str,
) -> dict[str, Any]:
    from app.custom_field_mapping import approved_raw_value, mapping_status
    from app.normalize import (
        _extract_sales,
        _parse_buffer_stock,
        _parse_urgent_state,
        normalize_sales_order,
    )

    mapped = normalize_sales_order(raw)
    number = str(mapped.get("number") or raw.get("number") or "").strip()
    if number != so_number:
        return {
            "ok": False,
            "probe": PROBE_NAME,
            "blocker": "document_number_mismatch",
            "expected_so_hash": _so_hash(so_number),
            "actual_so_hash": _so_hash(number) if number else None,
        }

    sales_name, sales_source = _extract_sales(raw)
    sales_paths = discover_sales_paths(raw)
    ship = discover_pengiriman_paths(raw)
    cf4 = cf_slot_presence(raw, 4)
    cf5 = cf_slot_presence(raw, 5)

    owner_status_raw = approved_raw_value(raw, scope="header", kind="order_priority")
    owner_buffer_raw = approved_raw_value(raw, scope="header", kind="buffer")
    urgent_class = classify_urgent(mapped.get("urgent_state"))
    buffer_class = classify_buffer(mapped.get("buffer_stock"))

    # Presence taxonomy for CF slots (no values leaked).
    def presence_class(slot: dict[str, str], mapped_class: str) -> str:
        if slot["value_present"] == "false":
            return "absent"
        if mapped_class == "unknown":
            return "present_unrecognized_or_unparsed"
        return "present_mapped"

    matrix = [
        {
            "field": "Sales",
            "json_path": sales_paths[0] if sales_paths else "UNKNOWN",
            "all_json_paths": sales_paths,
            "present": bool(sales_paths),
            "classification": "mapped" if sales_name else "unknown",
            "verification": cmp_str(sales_name, expected["sales"]),
            "parser_source": sales_source,
        },
        {
            "field": "Pengiriman",
            "json_path": ship["proven_json_path"],
            "mapped_native_paths_present": ship["mapped_native_paths_present"],
            "unproven_candidate_paths_present": ship[
                "unproven_candidate_paths_present"
            ],
            "present": bool(
                ship["mapped_native_paths_present"]
                or ship["unproven_candidate_paths_present"]
            ),
            "classification": (
                "mapped"
                if mapped.get("expedition")
                else (
                    "unknown_path_candidate_only"
                    if ship["unproven_candidate_paths_present"]
                    else "unknown"
                )
            ),
            "verification": cmp_str(mapped.get("expedition"), expected["expedition"]),
        },
        {
            "field": "Status",
            "json_path": cf4["json_path"],
            "present": cf4["value_present"] == "true",
            "companion_label_present": cf4["companion_label_present"] == "true",
            "classification": urgent_class,
            "presence_class": presence_class(cf4, urgent_class),
            "verification": cmp_str(mapped.get("urgent_state"), expected["urgent_state"]),
            "owner_slot_hit": owner_status_raw is not None,
        },
        {
            "field": "Buffer",
            "json_path": cf5["json_path"],
            "present": cf5["value_present"] == "true",
            "companion_label_present": cf5["companion_label_present"] == "true",
            "classification": buffer_class,
            "presence_class": presence_class(cf5, buffer_class),
            "verification": cmp_bool(
                mapped.get("buffer_stock"), expected["buffer_stock"]
            ),
            "owner_slot_hit": owner_buffer_raw is not None,
            # Prove parsers accept Owner UI spacing without leaking values.
            "parser_accepts_non_spaced_hyphen": _parse_buffer_stock("Non - Buffer")
            is False,
            "parser_accepts_normal": _parse_urgent_state("Normal") == "normal",
        },
    ]

    return {
        "ok": True,
        "probe": PROBE_NAME,
        "so_hash": _so_hash(so_number),
        "mapping_contract": mapping_status(),
        "four_field_matrix": matrix,
        "security": {
            "raw_values_printed": False,
            "expected_values_printed": False,
            "so_number_printed": False,
            "customer_printed": False,
            "credentials_printed": False,
        },
    }


def load_expected_four(path: str, so_number: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError("expected_file_missing")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expected_schema_invalid")
    required = {"so_number", "sales", "expedition", "urgent_state", "buffer_stock"}
    if not required.issubset(data.keys()):
        raise ValueError("expected_missing_required")
    if str(data["so_number"]).strip() != so_number:
        raise ValueError("expected_so_mismatch")
    if not isinstance(data["buffer_stock"], bool):
        raise ValueError("expected_schema_invalid")
    return {
        "so_number": so_number,
        "sales": str(data["sales"]).strip(),
        "expedition": str(data["expedition"]).strip(),
        "urgent_state": str(data["urgent_state"]).strip(),
        "buffer_stock": bool(data["buffer_stock"]),
    }


async def async_main(env_file: str, expected_file: str, so_number: str) -> int:
    slice1l = _load_slice1l()
    slice1l.silence_sensitive_loggers()
    slice1l._HTTP_METHODS_EXECUTED.clear()
    report: dict[str, Any] = {
        "ok": False,
        "probe": PROBE_NAME,
        "so_hash": _so_hash(so_number) if so_number else None,
    }
    try:
        if not so_number or not expected_file:
            report["blocker"] = "so_number_and_expected_required"
            print(json.dumps(report, indent=2))
            return 2
        expected = load_expected_four(expected_file, so_number)
        slice1l.load_env_file(env_file)
        from app.accurate_client import AccurateClient
        from app.config import settings

        if str(getattr(settings, "gateway_mode", "")).lower() != "live":
            report["blocker"] = "GATEWAY_MODE_must_be_live"
            print(json.dumps(report, indent=2))
            return 2
        client = AccurateClient()
        so_id = await slice1l.resolve_exact_so_id(client, so_number)
        slice1l._record_executed("GET /accurate/api/sales-order/detail.do")
        data = await client._request(
            "GET",
            "/accurate/api/sales-order/detail.do",
            params={"id": so_id},
        )
        raw = data.get("d") or data.get("data") or data
        if not isinstance(raw, dict):
            report["blocker"] = "accurate_detail_shape"
            print(json.dumps(report, indent=2))
            return 1
        built = build_four_field_report(raw, expected, so_number)
        built["http"] = {
            "allowed_methods": list(slice1l._ALLOWED_HTTP_METHODS),
            "executed_methods": list(slice1l._HTTP_METHODS_EXECUTED),
        }
        print(json.dumps(built, indent=2, ensure_ascii=False))
        return 0 if built.get("ok") else 1
    except Exception as exc:  # noqa: BLE001 — sanitized exit only
        report["error"] = slice1l._sanitize_exc(exc)
        report["blocker"] = "probe_runtime_error"
        print(json.dumps(report, indent=2))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 90 four-field sanitized probe")
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    parser.add_argument("--expected-file", default="")
    parser.add_argument("--so-number", default="")
    parser.add_argument("--syntax-check-only", action="store_true")
    args = parser.parse_args()
    if args.syntax_check_only:
        print(
            json.dumps(
                {
                    "ok": True,
                    "syntax_check_only": True,
                    "probe": PROBE_NAME,
                    "executed_live": False,
                },
                indent=2,
            )
        )
        return 0
    return asyncio.run(async_main(args.env_file, args.expected_file, args.so_number))


if __name__ == "__main__":
    raise SystemExit(main())
