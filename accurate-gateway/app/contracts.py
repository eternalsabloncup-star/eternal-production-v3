"""Map internal normalized docs → Production V3 gateway response contracts."""

from __future__ import annotations

from typing import Any


def so_list_row(row: dict[str, Any]) -> dict[str, Any]:
    customer = row.get("customer")
    if isinstance(customer, dict):
        customer_out: Any = customer.get("name") or customer.get("id") or ""
        customer_id = customer.get("id")
    else:
        customer_out = customer
        customer_id = None
    branch = row.get("branch")
    if isinstance(branch, dict):
        branch_id = branch.get("id") or ""
        branch_name = branch.get("name") or ""
    else:
        branch_id = str(row.get("branch_id") or "")
        branch_name = str(branch or "")
    so_number = str(row.get("number") or "")
    # Customer PO only when explicitly provided — never fabricate from SO number.
    raw_po = row.get("po_number")
    customer_po = (
        str(raw_po).strip()
        if raw_po is not None and str(raw_po).strip()
        else None
    )
    accurate_id = str(row.get("accurate_id") or row.get("id") or "").strip() or None
    return {
        "accurate_id": accurate_id,
        "number": so_number,
        "po_number": customer_po,
        "customer": customer_out,
        "customer_id": customer_id,
        "outlet": branch_name or None,
        "branch_id": branch_id or None,
        "branch": branch if isinstance(branch, dict) else {"id": branch_id, "name": branch_name},
        "status": row.get("status"),
        "currency": row.get("currency"),
        "total": row.get("total"),
        "order_date": row.get("order_date"),
        "sales": row.get("sales"),
    }


def so_detail(row: dict[str, Any]) -> dict[str, Any]:
    base = so_list_row(row)
    lines_in = row.get("line_items") or []
    lines: list[dict[str, Any]] = []
    total_qty = 0.0
    if isinstance(lines_in, list):
        for li in lines_in:
            if not isinstance(li, dict):
                continue
            qty = float(li.get("qty") or li.get("quantity") or 0)
            total_qty += qty
            lines.append(
                {
                    "accurate_line_id": li.get("accurate_line_id") or li.get("id"),
                    "accurate_item_id": li.get("accurate_item_id") or li.get("item_id"),
                    "item_code": li.get("sku") or li.get("item_code") or "",
                    "name": li.get("description") or li.get("name") or "",
                    "quantity": qty,
                    "unit": li.get("uom") or li.get("unit") or "",
                    "color": li.get("color"),
                    "notes": li.get("notes"),
                    "unit_price": li.get("unit_price"),
                }
            )
    base.update(
        {
            "line_items": lines,
            "total_quantity": row.get("total_quantity")
            if row.get("total_quantity") is not None
            else total_qty,
            "links": row.get("links") or {},
            "address": row.get("address"),
            "recipient": row.get("recipient"),
            "payment_terms": row.get("payment_terms"),
            "notes": row.get("notes"),
        }
    )
    return base


def receipt_contract(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row)


def delivery_note_contract(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row)
