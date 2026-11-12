#!/usr/bin/env python3
"""Step 90/102 — sanitized four-field Accurate Live evidence probe.

Scope only:
  1) Sales / Penjual
  2) Ekspedisi / Pengiriman
  3) Status Pesanan (Owner H CF4)
  4) Buffer / Non-Buffer (Owner H CF5)

Modes:
  - verify (default): requires --expected-file; MATCH/MISMATCH/UNKNOWN
  - --discover-only: --expected-file optional; JSON paths + parser classes only

Safety:
  - GET sales-order list/detail only; POST api-token.do auth bootstrap only.
  - Never print credentials, tokens, customer data, SO numbers, raw payloads,
    or field values — only JSON path names + classifications.
  - Does not invent new mappings; Pengiriman candidate keys are presence-only
    and never marked resolved without a normalizer-mapped path.
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


def _presence_class(slot: dict[str, str], mapped_class: str) -> str:
    if slot["value_present"] == "false":
        return "absent"
    if mapped_class == "unknown":
        return "present_unrecognized_or_unparsed"
    return "present_mapped"


def build_four_field_report(
    raw: dict[str, Any],
    expected: dict[str, Any] | None,
    so_number: str,
    *,
    discover_only: bool = False,
) -> dict[str, Any]:
    """Build sanitized four-field matrix.

    discover_only=True: no expected file; report JSON paths + parser classes only
    (no MATCH/MISMATCH verification). Never prints field values.
    """
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
            "mode": "discover" if discover_only else "verify",
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

    sales_row: dict[str, Any] = {
        "field": "Sales",
        "json_path": sales_paths[0] if sales_paths else "UNKNOWN",
        "all_json_paths": sales_paths,
        "normalizer_supported_paths": sales_paths,  # discovery from actual keys present
        "present": bool(sales_paths),
        "classification": "mapped" if sales_name else "unknown",
        "parser_source": sales_source,
        "normalizer_supported": True,  # salesman* keys are already supported
    }
    peng_row: dict[str, Any] = {
        "field": "Pengiriman",
        "json_path": ship["proven_json_path"],
        "mapped_native_paths_present": ship["mapped_native_paths_present"],
        "unproven_candidate_paths_present": ship["unproven_candidate_paths_present"],
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
        # Candidate presence alone never means RESOLVED.
        "resolved": bool(mapped.get("expedition")),
        "normalizer_supported": bool(ship["mapped_native_paths_present"]),
    }
    status_row: dict[str, Any] = {
        "field": "Status",
        "json_path": cf4["json_path"],
        "present": cf4["value_present"] == "true",
        "companion_label_present": cf4["companion_label_present"] == "true",
        "classification": urgent_class,
        "presence_class": _presence_class(cf4, urgent_class),
        "owner_slot_hit": owner_status_raw is not None,
        "normalizer_supported": True,  # Owner CF4
    }
    buffer_row: dict[str, Any] = {
        "field": "Buffer",
        "json_path": cf5["json_path"],
        "present": cf5["value_present"] == "true",
        "companion_label_present": cf5["companion_label_present"] == "true",
        "classification": buffer_class,
        "presence_class": _presence_class(cf5, buffer_class),
        "owner_slot_hit": owner_buffer_raw is not None,
        "normalizer_supported": True,  # Owner CF5
        "parser_accepts_non_spaced_hyphen": _parse_buffer_stock("Non - Buffer")
        is False,
        "parser_accepts_normal": _parse_urgent_state("Normal") == "normal",
    }

    if not discover_only:
        if expected is None:
            raise ValueError("expected_required_unless_discover_only")
        sales_row["verification"] = cmp_str(sales_name, expected["sales"])
        peng_row["verification"] = cmp_str(
            mapped.get("expedition"), expected["expedition"]
        )
        status_row["verification"] = cmp_str(
            mapped.get("urgent_state"), expected["urgent_state"]
        )
        buffer_row["verification"] = cmp_bool(
            mapped.get("buffer_stock"), expected["buffer_stock"]
        )

    return {
        "ok": True,
        "probe": PROBE_NAME,
        "mode": "discover" if discover_only else "verify",
        "so_hash": _so_hash(so_number),
        "identity": {"number_match": "yes"},
        "mapping_contract": mapping_status(),
        "four_field_matrix": [sales_row, peng_row, status_row, buffer_row],
        "security": {
            "raw_values_printed": False,
            "expected_values_printed": False,
            "so_number_printed": False,
            "customer_printed": False,
            "credentials_printed": False,
            "discover_only": discover_only,
        },
    }


def build_discovery_report(raw: dict[str, Any], so_number: str) -> dict[str, Any]:
    """Step 102 — path/classification discovery without expected values."""
    return build_four_field_report(raw, None, so_number, discover_only=True)


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


_PROBE_STAGES = (
    "load_config",
    "init_client",
    "resolve_so",
    "fetch_detail",
    "normalize_four_fields",
    "complete",
)


def classify_blocker(exc: BaseException, stage: str, safe_codes: frozenset[str]) -> str:
    """Map exception → allowlisted blocker; never invent sensitive detail."""
    raw_code = getattr(exc, "code", None)
    if isinstance(raw_code, str) and raw_code in safe_codes:
        return raw_code
    if stage == "load_config":
        if isinstance(exc, FileNotFoundError):
            return "env_file_missing"
        if isinstance(exc, PermissionError):
            return "env_file_unreadable"
        if isinstance(exc, ValueError) and str(exc) in safe_codes:
            return str(exc)
    if stage == "fetch_detail" and type(exc).__name__ == "AccurateUpstreamError":
        # code already checked above; unknown upstream → generic
        return "probe_runtime_error"
    return "probe_runtime_error"


def failure_report(
    *,
    slice1l: Any,
    stage: str,
    exc: BaseException,
    mode: str,
    so_number: str | None,
) -> dict[str, Any]:
    """Sanitized failure payload with explicit stage (no messages/tracebacks)."""
    safe_codes = getattr(slice1l, "_SAFE_ERROR_CODES", frozenset())
    error = slice1l._sanitize_exc(exc)
    blocker = classify_blocker(exc, stage, safe_codes)
    # Prefer sanitized allowlisted code when present.
    if error.get("code") in safe_codes and error.get("code") != "probe_runtime_error":
        blocker = error["code"]
    return {
        "ok": False,
        "probe": PROBE_NAME,
        "mode": mode,
        "stage": stage,
        "blocker": blocker,
        "error": error,
        "so_hash": _so_hash(so_number) if so_number else None,
        "http": {
            "allowed_methods": list(slice1l._ALLOWED_HTTP_METHODS),
            "executed_methods": list(slice1l._HTTP_METHODS_EXECUTED),
        },
        "security": {
            "raw_values_printed": False,
            "exception_message_printed": False,
            "traceback_printed": False,
            "credentials_printed": False,
            "so_number_printed": False,
        },
    }


async def async_main(
    env_file: str,
    expected_file: str,
    so_number: str,
    *,
    discover_only: bool = False,
) -> int:
    slice1l = _load_slice1l()
    slice1l.silence_sensitive_loggers()
    slice1l._HTTP_METHODS_EXECUTED.clear()
    mode = "discover" if discover_only else "verify"
    stage = "load_config"
    report: dict[str, Any] = {
        "ok": False,
        "probe": PROBE_NAME,
        "mode": mode,
        "stage": stage,
        "so_hash": _so_hash(so_number) if so_number else None,
    }
    try:
        if not so_number:
            report["blocker"] = "so_number_required"
            report["stage"] = "load_config"
            print(json.dumps(report, indent=2))
            return 2
        if not discover_only and not expected_file:
            report["blocker"] = "expected_file_required_unless_discover_only"
            report["stage"] = "load_config"
            print(json.dumps(report, indent=2))
            return 2

        stage = "load_config"
        expected = (
            None if discover_only else load_expected_four(expected_file, so_number)
        )
        slice1l.load_env_file(env_file)
        from app.config import settings

        if str(getattr(settings, "gateway_mode", "")).lower() != "live":
            report["blocker"] = "GATEWAY_MODE_must_be_live"
            report["stage"] = "load_config"
            report["http"] = {
                "allowed_methods": list(slice1l._ALLOWED_HTTP_METHODS),
                "executed_methods": list(slice1l._HTTP_METHODS_EXECUTED),
            }
            print(json.dumps(report, indent=2))
            return 2

        stage = "init_client"
        from app.accurate_client import AccurateClient

        client = AccurateClient()

        stage = "resolve_so"
        so_id = await slice1l.resolve_exact_so_id(client, so_number)

        stage = "fetch_detail"
        slice1l._record_executed("GET /accurate/api/sales-order/detail.do")
        data = await client._request(
            "GET",
            "/accurate/api/sales-order/detail.do",
            params={"id": so_id},
        )
        raw = data.get("d") or data.get("data") or data
        if not isinstance(raw, dict):
            report["blocker"] = "accurate_detail_shape"
            report["stage"] = "fetch_detail"
            report["http"] = {
                "allowed_methods": list(slice1l._ALLOWED_HTTP_METHODS),
                "executed_methods": list(slice1l._HTTP_METHODS_EXECUTED),
            }
            print(json.dumps(report, indent=2))
            return 1

        stage = "normalize_four_fields"
        built = build_four_field_report(
            raw, expected, so_number, discover_only=discover_only
        )
        stage = "complete"
        built["stage"] = stage
        built["http"] = {
            "allowed_methods": list(slice1l._ALLOWED_HTTP_METHODS),
            "executed_methods": list(slice1l._HTTP_METHODS_EXECUTED),
        }
        print(json.dumps(built, indent=2, ensure_ascii=False))
        return 0 if built.get("ok") else 1
    except Exception as exc:  # noqa: BLE001 — sanitized exit only
        fail = failure_report(
            slice1l=slice1l,
            stage=stage,
            exc=exc,
            mode=mode,
            so_number=so_number or None,
        )
        print(json.dumps(fail, indent=2))
        return 1 if stage not in {"load_config"} else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Step 90/102 four-field sanitized probe (verify or discover-only)"
    )
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    parser.add_argument("--expected-file", default="")
    parser.add_argument("--so-number", default="")
    parser.add_argument("--syntax-check-only", action="store_true")
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Discover JSON paths + parser classes without expected-file MATCH.",
    )
    args = parser.parse_args()
    if args.syntax_check_only:
        print(
            json.dumps(
                {
                    "ok": True,
                    "syntax_check_only": True,
                    "probe": PROBE_NAME,
                    "executed_live": False,
                    "supports_discover_only": True,
                },
                indent=2,
            )
        )
        return 0
    return asyncio.run(
        async_main(
            args.env_file,
            args.expected_file,
            args.so_number,
            discover_only=bool(args.discover_only),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
