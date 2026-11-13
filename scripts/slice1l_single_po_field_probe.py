#!/usr/bin/env python3
"""Slice 1L / Step 43B — sanitized secure single-PO Accurate Live field probe.

Business expected values are NEVER hardcoded. Provide them via --expected-file
(JSON on VPS, mode 0600, outside git) and --so-number.

Safety:
  - Read-only business GETs only (sales-order list resolve + detail by id).
  - Accurate api-token.do POST is auth bootstrap only; recorded only when proven.
  - No fixtures in live mode. No ERP V1. No Gateway/Backend/Frontend mutation.
  - Never print credentials, raw payloads, customer/sales names, addresses,
    item codes, custom-field values, expected JSON contents, paths, or SO numbers.
  - Unlabeled charField slots are never treated as semantic proof of a field.

Credentials:
  Load from /etc/epv3/gateway.env (VPS). Do not export secrets into shell history.

Exit codes:
  0 = probe completed (comparisons may include MISMATCH/UNKNOWN)
  1 = live/runtime failure
  2 = credentials / mode / expected-file / identity gate failed
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "accurate-gateway"))

DEFAULT_ENV_FILE = "/etc/epv3/gateway.env"

_ALLOWED_ENV_KEYS = frozenset(
    {
        "GATEWAY_MODE",
        "ACCURATE_API_TOKEN",
        "ACCURATE_SIGNATURE_SECRET",
        "ACCURATE_DATABASE_ID",
        "ACCURATE_ACCOUNT_BASE",
        "GATEWAY_M2M_TOKEN",
        "GATEWAY_APP_ENV",
    }
)

_ALLOWED_HTTP_METHODS = (
    "POST /api/api-token.do (auth bootstrap only)",
    "GET /accurate/api/sales-order/list.do",
    "GET /accurate/api/sales-order/detail.do",
)

_SAFE_EXCEPTION_TYPES = frozenset(
    {
        "AccurateUpstreamError",
        "FileNotFoundError",
        "OSError",
        "PermissionError",
        "ValueError",
        "TypeError",
        "RuntimeError",
        "TimeoutError",
        "JSONDecodeError",
        "KeyError",
        "ExpectedFileError",
    }
)

_SAFE_ERROR_CODES = frozenset(
    {
        "accurate_credentials_missing",
        "accurate_api_token_unreachable",
        "accurate_api_token_redirect_missing",
        "accurate_unreachable",
        "accurate_redirect_missing",
        "accurate_retryable",
        "accurate_auth_rejected",
        "accurate_not_found",
        "accurate_http_error",
        "accurate_invalid_json",
        "accurate_business_reject",
        "accurate_detail_shape",
        "accurate_identity_ambiguous",
        "accurate_list_shape",
        "env_file_missing",
        "env_file_unreadable",
        "GATEWAY_MODE_must_be_live",
        "detail_number_mismatch",
        "detail_id_invalid",
        "detail_id_mismatch_vs_resolved",
        "document_number_mismatch",
        "probe_runtime_error",
        "expected_file_missing",
        "expected_file_unreadable",
        "expected_json_invalid",
        "expected_schema_invalid",
        "expected_so_mismatch",
        "expected_qty_non_finite",
        "expected_duplicate_item_code",
        "expected_missing_required",
        "so_number_required",
        "expected_file_required",
    }
)

_HTTP_METHODS_EXECUTED: list[str] = []

_REQUIRED_EXPECTED_KEYS = frozenset(
    {
        "so_number",
        "sales",
        "expedition",
        "delivery_zone",
        "urgent_state",
        "buffer_stock",
        "total_quantity",
        "line_count",
        "lines",
    }
)

_REQUIRED_LINE_KEYS = frozenset({"item_code", "qty", "unit", "process", "color"})
_ALLOWED_PROCESS = frozenset({"print", "non_print"})


class ExpectedFileError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code if code in _SAFE_ERROR_CODES else "expected_schema_invalid"
        self.message = "redacted"
        super().__init__(self.code)


def _so_hash(number: str) -> str:
    return hashlib.sha256(number.encode("utf-8")).hexdigest()[:12]


def _item_code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()[:12]


def silence_sensitive_loggers() -> None:
    for name in (
        "httpx",
        "httpcore",
        "accurate_gateway.upstream",
        "accurate_gateway",
        "urllib3",
    ):
        logger = logging.getLogger(name)
        logger.disabled = True
        logger.propagate = False
        logger.setLevel(logging.CRITICAL + 1)


def _sanitize_exc(exc: BaseException) -> dict[str, str]:
    raw_type = type(exc).__name__
    safe_type = raw_type if raw_type in _SAFE_EXCEPTION_TYPES else "ProbeError"
    raw_code = getattr(exc, "code", None)
    if isinstance(raw_code, str) and raw_code in _SAFE_ERROR_CODES:
        safe_code = raw_code
    else:
        safe_code = "probe_runtime_error"
    return {"type": safe_type, "code": safe_code, "message": "redacted"}


def _base_report(*, so_number: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": False,
        "probe": "slice1l_single_po_field_probe",
        "http": {
            "allowed_methods": list(_ALLOWED_HTTP_METHODS),
            "executed_methods": list(_HTTP_METHODS_EXECUTED),
        },
    }
    if so_number:
        out["so_hash"] = _so_hash(so_number)
    return out


def load_env_file(path: str) -> dict[str, str]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError("env file missing")
    loaded: dict[str, str] = {}
    for raw_line in p.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key not in _ALLOWED_ENV_KEYS:
            continue
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        os.environ[key] = val
        loaded[key] = "<set>" if val else "<empty>"
    return loaded


def load_expected_file(path: str, so_number: str) -> dict[str, Any]:
    """Load and validate expected JSON. Never logs file contents or paths."""
    so_number = (so_number or "").strip()
    if not so_number:
        raise ExpectedFileError("so_number_required")
    p = Path(path)
    try:
        if not p.is_file():
            raise ExpectedFileError("expected_file_missing")
        raw_text = p.read_text(encoding="utf-8")
    except ExpectedFileError:
        raise
    except OSError as exc:
        raise ExpectedFileError("expected_file_unreadable") from exc
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ExpectedFileError("expected_json_invalid") from exc
    if not isinstance(data, dict):
        raise ExpectedFileError("expected_schema_invalid")

    missing = _REQUIRED_EXPECTED_KEYS - set(data.keys())
    if missing:
        raise ExpectedFileError("expected_missing_required")

    file_so = str(data.get("so_number") or "").strip()
    if file_so != so_number:
        raise ExpectedFileError("expected_so_mismatch")

    if not isinstance(data.get("sales"), str) or not str(data["sales"]).strip():
        raise ExpectedFileError("expected_missing_required")
    if not isinstance(data.get("expedition"), str) or not str(data["expedition"]).strip():
        raise ExpectedFileError("expected_missing_required")
    if not isinstance(data.get("delivery_zone"), str) or not str(
        data["delivery_zone"]
    ).strip():
        raise ExpectedFileError("expected_missing_required")
    if not isinstance(data.get("urgent_state"), str) or not str(
        data["urgent_state"]
    ).strip():
        raise ExpectedFileError("expected_missing_required")
    if not isinstance(data.get("buffer_stock"), bool):
        raise ExpectedFileError("expected_schema_invalid")

    try:
        total_qty = float(data["total_quantity"])
        line_count = int(data["line_count"])
    except (TypeError, ValueError) as exc:
        raise ExpectedFileError("expected_schema_invalid") from exc
    if not math.isfinite(total_qty):
        raise ExpectedFileError("expected_qty_non_finite")
    if line_count < 0:
        raise ExpectedFileError("expected_schema_invalid")

    lines = data.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ExpectedFileError("expected_missing_required")
    if len(lines) != line_count:
        raise ExpectedFileError("expected_schema_invalid")

    lines_by_code: dict[str, dict[str, Any]] = {}
    for entry in lines:
        if not isinstance(entry, dict):
            raise ExpectedFileError("expected_schema_invalid")
        if _REQUIRED_LINE_KEYS - set(entry.keys()):
            raise ExpectedFileError("expected_missing_required")
        code = str(entry.get("item_code") or "").strip()
        if not code:
            raise ExpectedFileError("expected_missing_required")
        if code in lines_by_code:
            raise ExpectedFileError("expected_duplicate_item_code")
        try:
            qty = float(entry["qty"])
        except (TypeError, ValueError) as exc:
            raise ExpectedFileError("expected_schema_invalid") from exc
        if not math.isfinite(qty):
            raise ExpectedFileError("expected_qty_non_finite")
        process = str(entry.get("process") or "").strip().lower()
        if process not in _ALLOWED_PROCESS:
            raise ExpectedFileError("expected_schema_invalid")
        unit = str(entry.get("unit") or "").strip()
        color = str(entry.get("color") or "").strip()
        if not unit or not color:
            raise ExpectedFileError("expected_missing_required")
        lines_by_code[code] = {
            "qty": qty,
            "unit": unit,
            "process": process,
            "color": color,
        }

    return {
        "so_number": so_number,
        "sales": str(data["sales"]).strip(),
        "expedition": str(data["expedition"]).strip(),
        "delivery_zone": str(data["delivery_zone"]).strip(),
        "urgent_state": str(data["urgent_state"]).strip(),
        "buffer_stock": bool(data["buffer_stock"]),
        "total_quantity": total_qty,
        "line_count": line_count,
        "lines_by_code": lines_by_code,
    }


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _label_present(row: dict[str, Any], index: int) -> bool:
    return any(
        _present(row.get(k))
        for k in (
            f"charField{index}Name",
            f"charField{index}Label",
            f"charField{index}Title",
            f"customField{index}Name",
            f"customField{index}Label",
            f"dataClassification{index}Name",
        )
    )


def _value_present(row: dict[str, Any], index: int) -> bool:
    return any(
        _present(row.get(k))
        for k in (
            f"charField{index}",
            f"customField{index}",
            f"dataClassification{index}",
        )
    )


def inventory_char_fields(row: dict[str, Any], *, scope: str) -> list[dict[str, Any]]:
    from app.custom_field_mapping import resolve_approved_slot

    field_scope = "header" if scope == "header" else "line"
    slots: list[dict[str, Any]] = []
    for i in range(1, 21):
        vp = _value_present(row, i)
        lp = _label_present(row, i)
        if not vp and not lp:
            continue
        raw_val = row.get(f"charField{i}")
        if raw_val is None:
            raw_val = row.get(f"customField{i}")
        if raw_val is None:
            raw_val = row.get(f"dataClassification{i}")
        companion = None
        for key in (
            f"charField{i}Name",
            f"charField{i}Label",
            f"charField{i}Title",
        ):
            if _present(row.get(key)):
                companion = str(row.get(key)).strip()
                break
        owner_kind = resolve_approved_slot(
            scope=field_scope,  # type: ignore[arg-type]
            slot=f"charField{i}",
            companion_label=companion,
        )
        if owner_kind:
            semantic = f"owner_approved_ordinal:{owner_kind}"
        elif vp and lp:
            semantic = "label_gated_parser_eligible"
        elif vp and not lp:
            semantic = "unlabeled_value_not_authoritative"
        else:
            semantic = "label_without_value"
        slots.append(
            {
                "scope": scope,
                "slot": f"charField{i}",
                "value_present": "yes" if vp else "no",
                "companion_label_present": "yes" if lp else "no",
                "value_type": type(raw_val).__name__ if vp else None,
                "semantic_mapping": semantic,
            }
        )
    return slots


def cmp_str(actual: Any, expected: str) -> str:
    if actual is None or (isinstance(actual, str) and not actual.strip()):
        return "UNKNOWN"
    if not isinstance(actual, str):
        actual = str(actual)
    if actual.strip().lower() == expected.strip().lower():
        return "MATCH"
    return "MISMATCH"


def cmp_bool(actual: Any, expected: bool) -> str:
    if actual is None:
        return "UNKNOWN"
    if isinstance(actual, bool):
        return "MATCH" if actual is expected else "MISMATCH"
    return "UNKNOWN"


def cmp_num(actual: Any, expected: float) -> str:
    if actual is None:
        return "UNKNOWN"
    try:
        num = float(actual)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if not math.isfinite(num):
        return "UNKNOWN"
    return "MATCH" if num == float(expected) else "MISMATCH"


def qty_validity(raw_line: dict[str, Any]) -> dict[str, Any]:
    if "quantity" in raw_line:
        key = "quantity"
        raw = raw_line.get("quantity")
    elif "qty" in raw_line:
        key = "qty"
        raw = raw_line.get("qty")
    else:
        return {
            "source_field": None,
            "present": "no",
            "finite": "no",
            "official_zero": "no",
            "contract": "UNKNOWN_missing",
        }
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return {
            "source_field": key,
            "present": "no",
            "finite": "no",
            "official_zero": "no",
            "contract": "UNKNOWN_missing",
        }
    try:
        num = float(raw)
    except (TypeError, ValueError):
        return {
            "source_field": key,
            "present": "yes",
            "finite": "no",
            "official_zero": "no",
            "contract": "UNKNOWN_invalid",
        }
    if not math.isfinite(num):
        return {
            "source_field": key,
            "present": "yes",
            "finite": "no",
            "official_zero": "no",
            "contract": "UNKNOWN_invalid",
        }
    if num == 0.0:
        return {
            "source_field": key,
            "present": "yes",
            "finite": "yes",
            "official_zero": "yes",
            "contract": "official_zero",
        }
    return {
        "source_field": key,
        "present": "yes",
        "finite": "yes",
        "official_zero": "no",
        "contract": "valid_nonzero",
    }


def line_item_code(row: dict[str, Any]) -> str | None:
    item = row.get("item") if isinstance(row.get("item"), dict) else {}
    for key in ("itemNo", "no", "sku", "itemCode"):
        val = row.get(key)
        if _present(val):
            return str(val).strip()
    if isinstance(item, dict):
        for key in ("no", "itemNo", "sku", "code"):
            val = item.get(key)
            if _present(val):
                return str(val).strip()
    return None


def missing_reason(
    *,
    field: str,
    mapped_present: bool,
    label_path_hit: bool,
    native_candidate: bool,
) -> str:
    if mapped_present:
        return "mapped"
    if label_path_hit:
        return "label_matched_but_value_absent_or_unparsed"
    if native_candidate:
        return "native_key_absent_or_empty"
    return (
        f"{field}: no labeled custom-field hit and no native key; "
        "unlabeled charField values are not authoritative"
    )


def _record_executed(method_path: str) -> None:
    _HTTP_METHODS_EXECUTED.append(method_path)


async def resolve_exact_so_id(client: Any, so_number: str) -> int:
    from app.accurate_client import AccurateUpstreamError

    attempts: list[dict[str, Any]] = [
        {
            "fields": "id,number",
            "sp.pageSize": 20,
            "sp.page": 1,
            "filter.number.op": "EQUAL",
            "filter.number.val": so_number,
        },
        {
            "fields": "id,number",
            "sp.pageSize": 50,
            "sp.page": 1,
            "filter.keywords.op": "EQUAL",
            "filter.keywords.val": so_number,
        },
    ]
    exact_ids: list[int] = []
    for params in attempts:
        _record_executed("GET /accurate/api/sales-order/list.do")
        try:
            data = await client._request(
                "GET", "/accurate/api/sales-order/list.do", params=params
            )
        except AccurateUpstreamError as exc:
            if exc.status_code in {404, 502}:
                continue
            raise
        rows = data.get("d") or data.get("data") or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            number = str(row.get("number") or row.get("no") or "").strip()
            if number != so_number:
                continue
            if row.get("id") is None:
                continue
            try:
                exact_ids.append(int(row["id"]))
            except (TypeError, ValueError) as exc:
                raise AccurateUpstreamError(
                    "accurate_detail_shape",
                    "sales-order id tidak valid",
                    status_code=502,
                ) from exc
        if exact_ids:
            break
    unique = sorted(set(exact_ids))
    if not unique:
        raise AccurateUpstreamError(
            "accurate_not_found",
            "dokumen tidak ditemukan di Accurate",
            status_code=404,
        )
    if len(unique) > 1:
        raise AccurateUpstreamError(
            "accurate_identity_ambiguous",
            "multiple internal ids for document number",
            status_code=502,
        )
    return unique[0]


async def fetch_raw_detail(client: Any, so_id: int) -> dict[str, Any]:
    from app.accurate_client import AccurateUpstreamError

    _record_executed("GET /accurate/api/sales-order/detail.do")
    data = await client._request(
        "GET",
        "/accurate/api/sales-order/detail.do",
        params={"id": int(so_id)},
    )
    row = data.get("d") or data.get("data") or data
    if not isinstance(row, dict):
        raise AccurateUpstreamError(
            "accurate_detail_shape",
            "sales-order/detail shape tidak dikenali",
            status_code=502,
        )
    return row


def build_report(
    raw: dict[str, Any],
    expected: dict[str, Any],
    so_number: str,
) -> dict[str, Any]:
    from app.custom_field_mapping import approved_raw_value, mapping_status
    from app.normalize import (
        _COLOR_LABELS,
        _EXPEDITION_LABELS,
        _BUFFER_LABELS,
        _ORDER_STATUS_LABELS,
        _PROCESS_LABELS,
        _ZONE_LABELS,
        _custom_field_by_label,
        _extract_sales,
        normalize_sales_order,
    )

    mapped = normalize_sales_order(raw)
    owner_zone = approved_raw_value(raw, scope="header", kind="delivery_zone")
    owner_status = approved_raw_value(raw, scope="header", kind="order_priority")
    owner_buffer = approved_raw_value(raw, scope="header", kind="buffer")
    number = str(mapped.get("number") or raw.get("number") or "").strip()
    if number != so_number:
        return {
            "ok": False,
            "blocker": "document_number_mismatch",
            "expected_so_hash": _so_hash(so_number),
            "actual_so_hash": _so_hash(number) if number else None,
        }

    sales_name, sales_source = _extract_sales(raw)
    exp_label = _custom_field_by_label(raw, _EXPEDITION_LABELS)
    zone_label = _custom_field_by_label(raw, _ZONE_LABELS)
    buf_label = _custom_field_by_label(raw, _BUFFER_LABELS)
    status_label = _custom_field_by_label(raw, _ORDER_STATUS_LABELS)

    header_slots = inventory_char_fields(raw, scope="header")
    raw_lines = raw.get("detailItem") or raw.get("detailItems") or raw.get("items") or []
    if not isinstance(raw_lines, list):
        raw_lines = []

    lines_by_code: dict[str, dict[str, Any]] = {}
    duplicate_code_hashes: list[str] = []
    for row in raw_lines:
        if not isinstance(row, dict):
            continue
        code = line_item_code(row)
        if not code:
            continue
        if code in lines_by_code:
            duplicate_code_hashes.append(_item_code_hash(code))
            continue
        lines_by_code[code] = row

    mapped_lines = {
        str(li.get("sku") or "").strip(): li
        for li in (mapped.get("line_items") or [])
        if isinstance(li, dict) and str(li.get("sku") or "").strip()
    }

    expected_lines: dict[str, dict[str, Any]] = expected["lines_by_code"]
    item_reports: list[dict[str, Any]] = []
    for code, exp_line in expected_lines.items():
        raw_line = lines_by_code.get(code)
        mapped_line = mapped_lines.get(code)
        code_hash = _item_code_hash(code)
        if raw_line is None:
            item_reports.append(
                {
                    "item_code_hash": code_hash,
                    "found": "no",
                    "pdf_compare": {
                        "qty": "UNKNOWN",
                        "process": "UNKNOWN",
                        "color": "UNKNOWN",
                        "unit": "UNKNOWN",
                    },
                    "quantity_validity": {"contract": "UNKNOWN_missing_line"},
                    "charField_slots": [],
                    "parser_sources": {
                        "process_label_hit": False,
                        "color_label_hit": False,
                    },
                    "missing_mapping_reason": "item_code_not_present_on_detail",
                }
            )
            continue

        process_hit = bool(_custom_field_by_label(raw_line, _PROCESS_LABELS))
        color_hit = bool(_custom_field_by_label(raw_line, _COLOR_LABELS))
        owner_process = approved_raw_value(
            raw_line, scope="line", kind="production_process"
        )
        owner_color = approved_raw_value(raw_line, scope="line", kind="color")
        process_actual = (mapped_line or {}).get("production_process")
        color_actual = (mapped_line or {}).get("color")
        qty_actual = (mapped_line or {}).get("qty")
        unit_actual = (mapped_line or {}).get("uom")

        item_reports.append(
            {
                "item_code_hash": code_hash,
                "found": "yes",
                "matched_by": "item_code",
                "pdf_compare": {
                    "qty": cmp_num(qty_actual, exp_line["qty"]),
                    "process": cmp_str(process_actual, exp_line["process"]),
                    "color": cmp_str(
                        str(color_actual).upper() if color_actual else None,
                        str(exp_line["color"]).upper(),
                    ),
                    "unit": cmp_str(unit_actual, exp_line["unit"]),
                },
                "quantity_validity": qty_validity(raw_line),
                "charField_slots": inventory_char_fields(
                    raw_line, scope=f"line:{code_hash}"
                ),
                "parser_sources": {
                    "process_label_hit": process_hit,
                    "color_label_hit": color_hit,
                    "process_source": (
                        "owner_accurate_configuration"
                        if owner_process is not None
                        else ("labeled_custom_field" if process_hit else "none")
                    ),
                    "color_source": (
                        "owner_accurate_configuration"
                        if owner_color is not None
                        else ("labeled_custom_field" if color_hit else "none")
                    ),
                    "process_mapped": process_actual
                    if process_actual in {"print", "non_print", "unknown"}
                    else "unknown",
                    "color_mapped_present": "yes" if _present(color_actual) else "no",
                },
                "missing_mapping_reason": {
                    "process": missing_reason(
                        field="process",
                        mapped_present=process_actual in {"print", "non_print"},
                        label_path_hit=process_hit or owner_process is not None,
                        native_candidate=_present(raw_line.get("production_process"))
                        or _present(raw_line.get("productionProcess")),
                    ),
                    "color": missing_reason(
                        field="color",
                        mapped_present=_present(color_actual),
                        label_path_hit=color_hit or owner_color is not None,
                        native_candidate=_present(raw_line.get("color"))
                        or _present(raw_line.get("warna")),
                    ),
                },
            }
        )

    expected_codes = set(expected_lines)
    extra_line_count = sum(1 for c in lines_by_code if c not in expected_codes)
    dup_unique = sorted(set(duplicate_code_hashes))

    native_expedition = any(
        _present(raw.get(k))
        for k in (
            "expedition",
            "expeditionName",
            "courier",
            "courierName",
            "shippingMethod",
            "shippingMethodName",
            "deliveryMethod",
        )
    )
    native_zone = any(
        _present(raw.get(k))
        for k in ("deliveryZone", "zone", "deliveryZoneName", "shipZone")
    )

    return {
        "ok": True,
        "probe": "slice1l_single_po_field_probe",
        "so_hash": _so_hash(so_number),
        "identity": {
            "number_match": "yes",
            "duplicate_item_code_count": len(duplicate_code_hashes),
            "duplicate_item_code_hashes": dup_unique,
            "ambiguous_rejected": "n/a_after_resolve",
        },
        "http": {
            "allowed_methods": list(_ALLOWED_HTTP_METHODS),
            "executed_methods": list(_HTTP_METHODS_EXECUTED),
        },
        "security": {
            "fixture_used": False,
            "business_writes": False,
            "auth_bootstrap_post_recorded": any(
                x.startswith("POST /api/api-token.do") for x in _HTTP_METHODS_EXECUTED
            ),
            "raw_values_printed": False,
            "expected_values_printed": False,
            "item_codes_printed": False,
            "env_path_printed": False,
            "expected_path_printed": False,
            "so_number_printed": False,
        },
        "line_count": {
            "accurate_detail_lines": len([r for r in raw_lines if isinstance(r, dict)]),
            "mapped_line_count": mapped.get("line_count"),
            "pdf_compare": cmp_num(mapped.get("line_count"), expected["line_count"]),
            "extra_lines_vs_pdf": extra_line_count,
        },
        "total_quantity": {
            "mapped_present": mapped.get("total_quantity") is not None,
            "pdf_compare": cmp_num(
                mapped.get("total_quantity"), expected["total_quantity"]
            ),
            "note": (
                "Gateway _qty maps missing/invalid quantity to 0.0; "
                "official zero and missing are not distinguishable in mapped total."
            ),
        },
        "header_fields": {
            "sales": {
                "pdf_compare": cmp_str(sales_name, expected["sales"]),
                "matching_parser_source": sales_source,
                "missing_mapping_reason": (
                    "mapped"
                    if sales_source
                    else "salesmanList/salesPerson* absent on detail"
                ),
            },
            "expedition": {
                "pdf_compare": cmp_str(mapped.get("expedition"), expected["expedition"]),
                "matching_parser_source": (
                    "labeled_custom_field" if exp_label else "native_or_absent"
                ),
                "label_path_hit": bool(exp_label),
                "missing_mapping_reason": missing_reason(
                    field="expedition",
                    mapped_present=_present(mapped.get("expedition")),
                    label_path_hit=bool(exp_label),
                    native_candidate=native_expedition,
                ),
            },
            "delivery_zone": {
                "pdf_compare": cmp_str(
                    mapped.get("delivery_zone"), expected["delivery_zone"]
                ),
                "matching_parser_source": (
                    "owner_accurate_configuration"
                    if owner_zone is not None
                    else ("labeled_custom_field" if zone_label else "native_or_absent")
                ),
                "label_path_hit": bool(zone_label),
                "missing_mapping_reason": missing_reason(
                    field="delivery_zone",
                    mapped_present=_present(mapped.get("delivery_zone")),
                    label_path_hit=bool(zone_label) or owner_zone is not None,
                    native_candidate=native_zone,
                ),
            },
            "status_pesanan": {
                "pdf_compare": cmp_str(
                    mapped.get("urgent_state"), expected["urgent_state"]
                ),
                "matching_parser_source": (
                    "owner_accurate_configuration"
                    if owner_status is not None
                    else ("labeled_custom_field" if status_label else "none")
                ),
                "label_path_hit": bool(status_label),
                "missing_mapping_reason": missing_reason(
                    field="status_pesanan",
                    mapped_present=_present(mapped.get("urgent_state")),
                    label_path_hit=bool(status_label) or owner_status is not None,
                    native_candidate=False,
                ),
            },
            "buffer": {
                "pdf_compare": cmp_bool(
                    mapped.get("buffer_stock"), expected["buffer_stock"]
                ),
                "matching_parser_source": (
                    "owner_accurate_configuration"
                    if owner_buffer is not None
                    else ("labeled_custom_field" if buf_label else "none")
                ),
                "label_path_hit": bool(buf_label),
                "missing_mapping_reason": missing_reason(
                    field="buffer",
                    mapped_present=mapped.get("buffer_stock") is not None,
                    label_path_hit=bool(buf_label) or owner_buffer is not None,
                    native_candidate=False,
                ),
            },
        },
        "mapping_contract": mapping_status(),
        "header_charField_slots": header_slots,
        "custom_field_lists_present": {
            key: isinstance(raw.get(key), list)
            for key in (
                "customFieldList",
                "charFieldList",
                "dataClassificationList",
            )
        },
        "items": item_reports,
        "rules": {
            "unlabeled_charField_not_semantic": True,
            "item_match": "by_official_item_code",
            "array_position_match": False,
        },
    }


def _note_auth_bootstrap_if_proven(client: Any) -> None:
    if any(x.startswith("POST /api/api-token.do") for x in _HTTP_METHODS_EXECUTED):
        return
    if getattr(client, "_host", None):
        _record_executed("POST /api/api-token.do (auth bootstrap only)")


async def async_main(env_file: str, expected_file: str, so_number: str) -> int:
    silence_sensitive_loggers()
    _HTTP_METHODS_EXECUTED.clear()
    so_number = (so_number or "").strip()
    report = _base_report(so_number=so_number or None)

    if not so_number:
        report["blocker"] = "so_number_required"
        report["error"] = _sanitize_exc(ExpectedFileError("so_number_required"))
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2
    if not (expected_file or "").strip():
        report["blocker"] = "expected_file_required"
        report["error"] = _sanitize_exc(ExpectedFileError("expected_file_required"))
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    try:
        expected = load_expected_file(expected_file, so_number)
    except ExpectedFileError as exc:
        report["blocker"] = exc.code
        report["error"] = _sanitize_exc(exc)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    try:
        loaded = load_env_file(env_file)
        report["env_keys_loaded"] = sorted(loaded.keys())
    except FileNotFoundError:
        report["blocker"] = "env_file_missing"
        report["error"] = _sanitize_exc(FileNotFoundError("env file missing"))
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2
    except OSError as exc:
        report["blocker"] = "env_file_unreadable"
        report["error"] = _sanitize_exc(exc)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    mode = (os.environ.get("GATEWAY_MODE") or "").strip().lower()
    if mode != "live":
        report["blocker"] = "GATEWAY_MODE_must_be_live"
        report["gateway_mode"] = "non_live" if mode else "unset"
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    try:
        from app.accurate_client import AccurateClient, AccurateUpstreamError
        from app.config import GatewaySettings, get_settings

        get_settings.cache_clear()
        settings = GatewaySettings()
        client = AccurateClient(settings)
        if not client.configured():
            report["blocker"] = "accurate_credentials_missing"
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 2

        so_id = await resolve_exact_so_id(client, so_number)
        _note_auth_bootstrap_if_proven(client)
        raw = await fetch_raw_detail(client, so_id)
        _note_auth_bootstrap_if_proven(client)

        detail_number = str(raw.get("number") or raw.get("no") or "").strip()
        if detail_number != so_number:
            report["blocker"] = "detail_number_mismatch"
            report["expected_so_hash"] = _so_hash(so_number)
            report["actual_so_hash"] = (
                _so_hash(detail_number) if detail_number else None
            )
            report["http"]["executed_methods"] = list(_HTTP_METHODS_EXECUTED)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 1

        try:
            detail_id = int(raw.get("id"))
        except (TypeError, ValueError):
            report["blocker"] = "detail_id_invalid"
            report["http"]["executed_methods"] = list(_HTTP_METHODS_EXECUTED)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 1
        if detail_id != so_id:
            report["blocker"] = "detail_id_mismatch_vs_resolved"
            report["http"]["executed_methods"] = list(_HTTP_METHODS_EXECUTED)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 1

        built = build_report(raw, expected, so_number)
        built["resolved_id_present"] = True
        print(json.dumps(built, indent=2, ensure_ascii=False))
        return 0 if built.get("ok") else 1
    except Exception as exc:  # noqa: BLE001
        from app.accurate_client import AccurateUpstreamError

        report["ok"] = False
        report["error"] = _sanitize_exc(exc)
        if isinstance(exc, AccurateUpstreamError) and exc.code in _SAFE_ERROR_CODES:
            report["blocker"] = exc.code
        else:
            report["blocker"] = "probe_runtime_error"
        report["http"]["executed_methods"] = list(_HTTP_METHODS_EXECUTED)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Secure single-PO Accurate Live field probe "
            "(sanitized MATCH/MISMATCH/UNKNOWN output only)."
        )
    )
    parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_FILE,
        help="Path to gateway env file (default: system VPS path).",
    )
    parser.add_argument(
        "--expected-file",
        default="",
        help="Path to expected JSON on VPS (mode 0600, outside git).",
    )
    parser.add_argument(
        "--so-number",
        default="",
        help="Exact Sales Order document number to probe.",
    )
    parser.add_argument(
        "--syntax-check-only",
        action="store_true",
        help="Exit 0 after import/argparse (no network, no expected file).",
    )
    args = parser.parse_args()
    if args.syntax_check_only:
        silence_sensitive_loggers()
        print(
            json.dumps(
                {
                    "ok": True,
                    "syntax_check_only": True,
                    "probe": "slice1l_single_po_field_probe",
                    "executed_live": False,
                    "http": {
                        "allowed_methods": list(_ALLOWED_HTTP_METHODS),
                        "executed_methods": [],
                    },
                },
                indent=2,
            )
        )
        return 0
    return asyncio.run(
        async_main(args.env_file, args.expected_file, args.so_number)
    )


if __name__ == "__main__":
    raise SystemExit(main())
