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
    buffer_stock = row.get("buffer_stock")
    if buffer_stock is not None and not isinstance(buffer_stock, bool):
        buffer_stock = None
    urgent_state = row.get("urgent_state")
    if urgent_state is not None:
        urgent_state = str(urgent_state).strip() or None
    sales = row.get("sales")
    if sales is not None:
        sales = str(sales).strip() or None
    sales_source = row.get("sales_source")
    if sales_source is not None:
        sales_source = str(sales_source).strip() or None
    return {
        "accurate_id": accurate_id,
        "number": so_number,
        "po_number": customer_po,
        "customer": customer_out,
        "customer_id": customer_id,
        "outlet": branch_name or None,
        "branch_id": branch_id or None,
        "branch_name": branch_name or None,
        "branch": branch if isinstance(branch, dict) else {"id": branch_id, "name": branch_name},
        "status": row.get("status"),
        "currency": row.get("currency"),
        "total": row.get("total"),
        "order_date": row.get("order_date"),
        "sales": sales,
        "sales_source": sales_source,
        # Nullable classifications — never coerce missing → false.
        "buffer_stock": buffer_stock,
        "urgent_state": urgent_state,
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
            process = li.get("production_process")
            if process is not None:
                process = str(process).strip().lower().replace(" ", "_")
            if process not in {"print", "non_print", "unknown"}:
                process = "unknown"
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
                    "production_process": process,
                }
            )
    line_count = row.get("line_count")
    if line_count is None:
        line_count = len(lines)
    base.update(
        {
            "line_items": lines,
            "total_quantity": row.get("total_quantity")
            if row.get("total_quantity") is not None
            else total_qty,
            "line_count": line_count,
            "links": row.get("links") or {},
            "address": row.get("address"),
            "recipient": row.get("recipient"),
            "payment_terms": row.get("payment_terms"),
            "created_by_user": row.get("created_by_user"),
            "expedition": row.get("expedition"),
            "estimated_delivery": row.get("estimated_delivery")
            or row.get("deadline"),
            "delivery_zone": row.get("delivery_zone"),
            "notes": row.get("notes"),
        }
    )
    return base


def receipt_contract(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row)


def delivery_note_contract(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row)
