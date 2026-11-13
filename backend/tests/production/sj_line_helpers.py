"""Accurate SJ line evidence helpers for Loading tests (no live Accurate)."""

from __future__ import annotations

from typing import Any


def sj_line_item(
    *,
    accurate_sj_line_id: str,
    so_line_id: str,
    quantity: float,
    unit_ratio: float = 1.0,
    accurate_so_id: str = "90001",
    accurate_item_id: str = "5001",
    sku: str = "SKU",
    loading_eligible: bool = True,
) -> dict[str, Any]:
    return {
        "sku": sku,
        "qty": quantity,
        "uom": "PCS",
        "accurate_sj_line_id": str(accurate_sj_line_id),
        "so_line_id": str(so_line_id),
        "accurate_so_id": str(accurate_so_id),
        "accurate_item_id": str(accurate_item_id),
        "quantity": quantity,
        "qty_verified": True,
        "unit_ratio": unit_ratio,
        "unit_ratio_verified": True,
        "line_identity_complete": True,
        "loading_eligible": loading_eligible,
        "identity_conflicts": [],
        "so_line_id_source": "detailItem.salesOrderDetailId",
        "so_line_field_semantics_verified": True,
        "so_line_cross_verified": False,
    }


def sj_delivery_note(
    *,
    sj_id: str,
    sj_number: str | None = None,
    so_number: str,
    branch_id: str = "branch-a",
    lines: list[dict[str, Any]],
    cancelled: bool = False,
) -> dict[str, Any]:
    return {
        "id": sj_id,
        "number": sj_number or sj_id,
        "status": "CANCELLED" if cancelled else "DELIVERED",
        "cancelled": cancelled,
        "verifiable": not cancelled,
        "sales_order_number": so_number,
        "branch": {"id": branch_id, "name": branch_id},
        "line_items": lines,
        "loading_eligible": bool(lines)
        and all(ln.get("loading_eligible") is True for ln in lines),
        "live_verified": False,
        "source": "fixture",
    }


def loading_body(
    *,
    accurate_sj_id: str,
    accurate_sj_number: str | None = None,
    accurate_sj_line_id: str,
    so_line_id: str,
    qty_physical: str,
    idempotency_key: str,
) -> dict[str, Any]:
    return {
        "accurate_sj_id": accurate_sj_id,
        "accurate_sj_number": accurate_sj_number or accurate_sj_id,
        "accurate_sj_line_id": accurate_sj_line_id,
        "so_line_id": so_line_id,
        "qty_physical": qty_physical,
        "idempotency_key": idempotency_key,
    }
