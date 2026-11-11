"""Normalize Accurate Online payloads into Production V3 gateway contracts."""

from __future__ import annotations

from typing import Any


def _party(raw: Any, id_key: str = "id", name_key: str = "name") -> dict[str, Any]:
    if isinstance(raw, dict):
        return {
            "id": str(raw.get(id_key) or raw.get("customerId") or raw.get("branchId") or ""),
            "name": str(raw.get(name_key) or raw.get("customerName") or raw.get("branchName") or ""),
        }
    return {"id": "", "name": str(raw or "")}


def _status(raw: dict[str, Any]) -> str:
    for key in ("statusName", "status", "charField1"):
        val = raw.get(key)
        if val is not None and str(val).strip():
            return str(val).strip().upper().replace(" ", "_")
    if raw.get("cancelled") or raw.get("isCancelled"):
        return "CANCELLED"
    return "UNKNOWN"


def _lines(raw: dict[str, Any]) -> list[dict[str, Any]]:
    detail = raw.get("detailItem") or raw.get("detailItems") or raw.get("items") or []
    if not isinstance(detail, list):
        return []
    out: list[dict[str, Any]] = []
    for row in detail:
        if not isinstance(row, dict):
            continue
        item = row.get("item") if isinstance(row.get("item"), dict) else {}
        out.append(
            {
                "sku": str(
                    row.get("itemNo")
                    or item.get("no")
                    or row.get("sku")
                    or row.get("itemId")
                    or ""
                ),
                "description": str(
                    row.get("detailName") or row.get("itemName") or item.get("name") or ""
                ),
                "qty": float(row.get("quantity") or row.get("qty") or 0),
                "uom": str(row.get("itemUnit") or row.get("unit") or row.get("uom") or ""),
                "unit_price": float(row.get("unitPrice") or row.get("price") or 0),
            }
        )
    return out


def _customer_po_number(raw: dict[str, Any]) -> str | None:
    """Customer-provided PO only — never copy Accurate SO number."""
    for key in (
        "poNumber",
        "poNo",
        "customerPoNumber",
        "customerPONumber",
        "purchaseOrderNumber",
        "purchaseOrderNo",
    ):
        val = raw.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def _document_id(raw: dict[str, Any]) -> str:
    for key in ("id", "salesOrderId", "soId"):
        val = raw.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def normalize_sales_order_list_item(raw: dict[str, Any]) -> dict[str, Any]:
    customer = raw.get("customer")
    if not isinstance(customer, dict):
        customer = {"id": raw.get("customerId"), "name": raw.get("customerName")}
    branch = raw.get("branch")
    if not isinstance(branch, dict):
        branch = {"id": raw.get("branchId"), "name": raw.get("branchName")}
    so_number = str(raw.get("number") or raw.get("no") or "")
    customer_po = _customer_po_number(raw)
    return {
        "id": _document_id(raw),
        "accurate_id": _document_id(raw),
        "number": so_number,
        # Real customer PO only; null when Accurate does not provide one.
        "po_number": customer_po,
        "status": _status(raw),
        "customer": _party(customer),
        "branch": _party(branch),
        "currency": str(raw.get("currency") or raw.get("currencyCode") or "IDR"),
        "total": float(raw.get("totalAmount") or raw.get("total") or 0),
        "order_date": raw.get("transDate") or raw.get("orderDate") or raw.get("order_date"),
    }


def normalize_sales_order(raw: dict[str, Any]) -> dict[str, Any]:
    base = normalize_sales_order_list_item(raw)
    base["line_items"] = _lines(raw)
    # Optional linked document hints when Accurate includes them.
    # Empty links are NOT payment/delivery verification.
    receipt_ids: list[str] = []
    delivery_ids: list[str] = []
    for key in ("salesReceipt", "salesReceipts", "receiptList"):
        block = raw.get(key)
        if isinstance(block, list):
            for r in block:
                if isinstance(r, dict):
                    rid = r.get("number") or r.get("id")
                    if rid:
                        receipt_ids.append(str(rid))
        elif isinstance(block, dict):
            rid = block.get("number") or block.get("id")
            if rid:
                receipt_ids.append(str(rid))
    for key in ("deliveryOrder", "deliveryOrders", "doList"):
        block = raw.get(key)
        if isinstance(block, list):
            for r in block:
                if isinstance(r, dict):
                    did = r.get("number") or r.get("id")
                    if did:
                        delivery_ids.append(str(did))
        elif isinstance(block, dict):
            did = block.get("number") or block.get("id")
            if did:
                delivery_ids.append(str(did))
    base["links"] = {
        "receipt_ids": receipt_ids,
        "delivery_note_ids": delivery_ids,
        "receipts_present": bool(receipt_ids),
        "delivery_notes_present": bool(delivery_ids),
        # Explicit: discovery hints only — never authority for gates.
        "evidence_authority": False,
    }
    return base


def _truthy_cancel(raw: dict[str, Any]) -> bool:
    status = _status(raw)
    if status in {"CANCELLED", "CANCELED", "VOID", "VOIDED"}:
        return True
    return bool(raw.get("cancelled") or raw.get("isCancelled") or raw.get("void"))


def _truthy_reverse(raw: dict[str, Any]) -> bool:
    status = _status(raw)
    if status in {"REVERSED", "REVERSE", "REVERSAL"}:
        return True
    return bool(raw.get("reversed") or raw.get("isReversed") or raw.get("hasReverse"))


def normalize_receipt(raw: dict[str, Any]) -> dict[str, Any]:
    cancelled = _truthy_cancel(raw)
    reversed_ = _truthy_reverse(raw)
    so_number = (
        raw.get("salesOrder")
        or raw.get("salesOrderNumber")
        or raw.get("soNumber")
        or ""
    )
    if isinstance(so_number, dict):
        so_number = so_number.get("number") or so_number.get("no") or ""
    customer = raw.get("customer")
    if not isinstance(customer, dict):
        customer = {"id": raw.get("customerId"), "name": raw.get("customerName")}
    branch = raw.get("branch")
    if not isinstance(branch, dict):
        branch = {"id": raw.get("branchId"), "name": raw.get("branchName")}
    status = _status(raw)
    verifiable = not cancelled and not reversed_ and status not in {
        "UNKNOWN",
        "DRAFT",
        "UNPOSTED",
    }
    return {
        "id": str(raw.get("id") or raw.get("number") or raw.get("no") or ""),
        "number": str(raw.get("number") or raw.get("no") or raw.get("id") or ""),
        "status": status,
        "sales_order_number": str(so_number or ""),
        "amount": float(raw.get("totalAmount") or raw.get("amount") or raw.get("paymentAmount") or 0),
        "currency": str(raw.get("currency") or raw.get("currencyCode") or "IDR"),
        "paid_at": raw.get("transDate") or raw.get("chequeDate") or raw.get("paidAt"),
        "customer": _party(customer),
        "branch": _party(branch),
        "reversed": reversed_,
        "cancelled": cancelled,
        "verifiable": verifiable,
    }


def normalize_delivery_note(raw: dict[str, Any]) -> dict[str, Any]:
    cancelled = _truthy_cancel(raw)
    so_number = (
        raw.get("salesOrder")
        or raw.get("salesOrderNumber")
        or raw.get("soNumber")
        or ""
    )
    if isinstance(so_number, dict):
        so_number = so_number.get("number") or so_number.get("no") or ""
    customer = raw.get("customer")
    if not isinstance(customer, dict):
        customer = {"id": raw.get("customerId"), "name": raw.get("customerName")}
    branch = raw.get("branch")
    if not isinstance(branch, dict):
        branch = {"id": raw.get("branchId"), "name": raw.get("branchName")}
    status = _status(raw)
    verifiable = not cancelled and status not in {"UNKNOWN", "DRAFT", "UNPOSTED", "CANCELLED"}
    return {
        "id": str(raw.get("id") or raw.get("number") or raw.get("no") or ""),
        "number": str(raw.get("number") or raw.get("no") or raw.get("id") or ""),
        "status": status,
        "sales_order_number": str(so_number or ""),
        "customer": _party(customer),
        "branch": _party(branch),
        "shipped_at": raw.get("shipDate") or raw.get("transDate") or raw.get("shippedAt"),
        "cancelled": cancelled,
        "verifiable": verifiable,
        "line_items": [
            {
                "sku": li.get("sku") or "",
                "qty": li.get("qty") or 0,
                "uom": li.get("uom") or "",
            }
            for li in _lines(raw)
        ],
    }
