"""Normalize Accurate Online payloads into Production V3 gateway contracts."""

from __future__ import annotations

from typing import Any


def _party(raw: Any, id_key: str = "id", name_key: str = "name") -> dict[str, Any]:
    if isinstance(raw, dict):
        return {
            "id": str(
                raw.get(id_key)
                or raw.get("customerId")
                or raw.get("branchId")
                or ""
            ),
            "name": str(
                raw.get(name_key)
                or raw.get("customerName")
                or raw.get("branchName")
                or ""
            ),
        }
    return {"id": "", "name": str(raw or "")}


def _status(raw: dict[str, Any]) -> str:
    for key in ("statusName", "status"):
        val = raw.get(key)
        if val is not None and str(val).strip():
            return str(val).strip().upper().replace(" ", "_")
    if raw.get("cancelled") or raw.get("isCancelled"):
        return "CANCELLED"
    return "UNKNOWN"


def _first_str(*values: Any) -> str | None:
    for val in values:
        if val is None:
            continue
        if isinstance(val, dict):
            nested = val.get("name") or val.get("number") or val.get("no")
            if nested is not None and str(nested).strip():
                return str(nested).strip()
            continue
        text = str(val).strip()
        if text:
            return text
    return None


def _sales_from_list(block: Any) -> list[str]:
    """Extract salesperson names from Accurate salesmanList-style arrays."""
    if not isinstance(block, list):
        return []
    names: list[str] = []
    for entry in block:
        if isinstance(entry, dict):
            name = _first_str(
                entry.get("name"),
                entry.get("salesmanName"),
                entry.get("salesPersonName"),
                entry.get("salespersonName"),
                entry.get("fullName"),
                entry.get("nama"),
            )
        else:
            name = _first_str(entry)
        if name:
            names.append(name)
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(names))


def _extract_sales(raw: dict[str, Any]) -> tuple[str | None, str | None]:
    """Official salesperson only — never confuse with document creator.

    Returns (name, source_field). source_field is for audit when missing/present.
    Accurate Online commonly nests sellers in salesmanList.
    """
    for list_key in (
        "salesmanList",
        "salesPersonList",
        "salespersonList",
        "salesList",
    ):
        names = _sales_from_list(raw.get(list_key))
        if names:
            return ", ".join(names), list_key

    nested_keys = (
        ("salesPerson", "salesPerson"),
        ("salesperson", "salesperson"),
        ("salesman", "salesman"),
        ("sales", "sales"),
    )
    for key, source in nested_keys:
        nested = raw.get(key)
        if isinstance(nested, dict):
            name = _first_str(
                nested.get("name"),
                nested.get("fullName"),
                nested.get("salesmanName"),
                nested.get("salesPersonName"),
            )
            if name:
                return name, source

    for key in (
        "salesPersonName",
        "salespersonName",
        "salesmanName",
        "salesName",
    ):
        name = _first_str(raw.get(key))
        if name:
            return name, key

    scalar = raw.get("sales")
    if not isinstance(scalar, dict):
        name = _first_str(scalar)
        if name:
            return name, "sales"
    return None, None


def _sales_name(raw: dict[str, Any]) -> str | None:
    name, _source = _extract_sales(raw)
    return name


def _created_by_user(raw: dict[str, Any]) -> str | None:
    nested = (
        raw.get("createdUser")
        or raw.get("createdByUser")
        or raw.get("inputUser")
        or raw.get("user")
    )
    if isinstance(nested, dict):
        name = _first_str(
            nested.get("name"),
            nested.get("fullName"),
            nested.get("email"),
        )
        if name:
            return name
    return _first_str(
        raw.get("createdByUserName"),
        raw.get("createdUserName"),
        raw.get("inputUserName"),
        raw.get("userName"),
        raw.get("createdBy") if not isinstance(raw.get("createdBy"), dict) else None,
    )


def _uom(row: dict[str, Any], item: dict[str, Any]) -> str:
    unit = row.get("itemUnit") or row.get("unit") or row.get("uom") or item.get("unit")
    if isinstance(unit, dict):
        return str(unit.get("name") or unit.get("code") or unit.get("id") or "")
    return str(unit or "")


def _qty(row: dict[str, Any]) -> float:
    raw = row.get("quantity")
    if raw is None:
        raw = row.get("qty")
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _explicit_production_process(row: dict[str, Any]) -> str:
    """Only exact print|non_print from an explicit production_process field.

    Never infer from charField*, numericField*, item flags, or name heuristics.
    Never treat blank as print (legacy V1 fallback is intentionally not copied).
    Missing/unrecognized → unknown.
    """
    raw = row.get("production_process")
    if raw is None:
        raw = row.get("productionProcess")
    if raw is None:
        return "unknown"
    normalized = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    if normalized in {"print", "non_print"}:
        return normalized
    # Display labels from verified Eternal classification only — not name heuristics.
    if normalized in {"cetak"}:
        return "print"
    if normalized in {"tidak_cetak", "noncetak", "non-cetak"}:
        return "non_print"
    return "unknown"


def _line_color(row: dict[str, Any], item: dict[str, Any]) -> str | None:
    return _first_str(
        row.get("color"),
        row.get("warna"),
        row.get("detailColor"),
        item.get("color"),
        item.get("warna"),
    )


def _line_notes(row: dict[str, Any]) -> str | None:
    return _first_str(
        row.get("notes"),
        row.get("detailNotes"),
        row.get("detailNote"),
        row.get("description2"),
        row.get("memo"),
    )


def _line_identity(row: dict[str, Any], item: dict[str, Any]) -> tuple[str | None, str | None]:
    """Preserve Accurate detailItem.id (and item id when present)."""
    line_id = row.get("id")
    if line_id is None:
        line_id = row.get("detailId") or row.get("salesOrderDetailId")
    item_id = row.get("itemId") or item.get("id")
    line_s = str(line_id).strip() if line_id is not None and str(line_id).strip() else None
    item_s = str(item_id).strip() if item_id is not None and str(item_id).strip() else None
    return line_s, item_s


def _lines(raw: dict[str, Any]) -> list[dict[str, Any]]:
    detail = raw.get("detailItem") or raw.get("detailItems") or raw.get("items") or []
    if not isinstance(detail, list):
        return []
    out: list[dict[str, Any]] = []
    for row in detail:
        if not isinstance(row, dict):
            continue
        item = row.get("item") if isinstance(row.get("item"), dict) else {}
        line_id, item_id = _line_identity(row, item)
        out.append(
            {
                "id": line_id,
                "accurate_line_id": line_id,
                "accurate_item_id": item_id,
                "item_id": item_id,
                "sku": str(
                    row.get("itemNo")
                    or item.get("no")
                    or row.get("sku")
                    or ""
                ),
                "description": str(
                    row.get("detailName")
                    or row.get("itemName")
                    or item.get("name")
                    or ""
                ),
                "qty": _qty(row),
                "uom": _uom(row, item),
                "unit_price": float(row.get("unitPrice") or row.get("price") or 0),
                "color": _line_color(row, item),
                "notes": _line_notes(row),
                # Slice 0: print candidates unproven unless explicit process field.
                "production_process": _explicit_production_process(row),
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


def _branch_party(raw: dict[str, Any]) -> dict[str, Any]:
    branch = raw.get("branch")
    if not isinstance(branch, dict):
        branch = {
            "id": raw.get("branchId"),
            "name": raw.get("branchName"),
        }
    party = _party(branch)
    if not party.get("name"):
        party["name"] = _first_str(raw.get("branchName")) or ""
    if not party.get("id"):
        party["id"] = _first_str(raw.get("branchId")) or ""
    return party


def normalize_sales_order_list_item(raw: dict[str, Any]) -> dict[str, Any]:
    customer = raw.get("customer")
    if not isinstance(customer, dict):
        customer = {"id": raw.get("customerId"), "name": raw.get("customerName")}
    branch = _branch_party(raw)
    so_number = str(raw.get("number") or raw.get("no") or "")
    customer_po = _customer_po_number(raw)
    sales, sales_source = _extract_sales(raw)
    return {
        "id": _document_id(raw),
        "accurate_id": _document_id(raw),
        "number": so_number,
        # Real customer PO only; null when Accurate does not provide one.
        "po_number": customer_po,
        "status": _status(raw),
        "customer": _party(customer),
        "branch": branch,
        "currency": str(raw.get("currency") or raw.get("currencyCode") or "IDR"),
        "total": float(raw.get("totalAmount") or raw.get("total") or 0),
        "order_date": raw.get("transDate") or raw.get("orderDate") or raw.get("order_date"),
        "sales": sales,
        # Audit: which Accurate field supplied sales; null ⇒ absent (not creator fallback).
        "sales_source": sales_source,
        # Slice 0: Buffer/Urgent missing in live Accurate sample — never invent false.
        "buffer_stock": None,
        "urgent_state": None,
    }


def normalize_sales_order(raw: dict[str, Any]) -> dict[str, Any]:
    base = normalize_sales_order_list_item(raw)
    lines = _lines(raw)
    base["line_items"] = lines
    base["total_quantity"] = sum(float(li.get("qty") or 0) for li in lines)
    base["line_count"] = len(lines)
    # Re-resolve on full detail payload (list may omit salesmanList).
    sales, sales_source = _extract_sales(raw)
    base["sales"] = sales
    base["sales_source"] = sales_source
    base["created_by_user"] = _created_by_user(raw)
    base["address"] = _first_str(
        raw.get("toAddress"),
        raw.get("shipAddress"),
        raw.get("address"),
        raw.get("customerAddress"),
    )
    base["recipient"] = _first_str(
        raw.get("recipient"),
        raw.get("toName"),
        raw.get("shipToName"),
    )
    base["payment_terms"] = _first_str(
        raw.get("paymentTermName"),
        raw.get("paymentTerms"),
        raw.get("paymentTerm"),
        raw.get("termName"),
        raw.get("paymentTerm") if not isinstance(raw.get("paymentTerm"), dict) else None,
        (raw.get("paymentTerm") or {}).get("name")
        if isinstance(raw.get("paymentTerm"), dict)
        else None,
    )
    base["expedition"] = _first_str(
        raw.get("expedition"),
        raw.get("expeditionName"),
        raw.get("courier"),
        raw.get("shippingInfo"),
    )
    base["estimated_delivery"] = (
        raw.get("estimatedDeliveryDate")
        or raw.get("shipDate")
        or raw.get("dueDate")
        or raw.get("deliveryDate")
    )
    base["delivery_zone"] = _first_str(
        raw.get("deliveryZone"),
        raw.get("zone"),
        raw.get("deliveryZoneName"),
    )
    base["notes"] = _first_str(
        raw.get("description"),
        raw.get("notes"),
        raw.get("memo"),
        raw.get("remark"),
    )
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
    branch = _branch_party(raw)
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
        "branch": branch,
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
    branch = _branch_party(raw)
    status = _status(raw)
    verifiable = not cancelled and status not in {"UNKNOWN", "DRAFT", "UNPOSTED", "CANCELLED"}
    return {
        "id": str(raw.get("id") or raw.get("number") or raw.get("no") or ""),
        "number": str(raw.get("number") or raw.get("no") or raw.get("id") or ""),
        "status": status,
        "sales_order_number": str(so_number or ""),
        "customer": _party(customer),
        "branch": branch,
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
