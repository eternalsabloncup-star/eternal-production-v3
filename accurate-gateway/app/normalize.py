"""Normalize Accurate Online payloads into Production V3 gateway contracts."""

from __future__ import annotations

import math
from typing import Any

from app.custom_field_mapping import approved_raw_value


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
            nested = (
                entry.get("salesman")
                or entry.get("salesPerson")
                or entry.get("salesperson")
                or entry.get("sales")
            )
            name = _first_str(
                entry.get("name"),
                entry.get("salesmanName"),
                entry.get("salesPersonName"),
                entry.get("salespersonName"),
                entry.get("fullName"),
                entry.get("nama"),
                nested if isinstance(nested, dict) else None,
                nested.get("name") if isinstance(nested, dict) else None,
                nested.get("fullName") if isinstance(nested, dict) else None,
                nested.get("salesmanName") if isinstance(nested, dict) else None,
                nested.get("salesPersonName") if isinstance(nested, dict) else None,
            )
        else:
            name = _first_str(entry)
        if name:
            names.append(name)
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(names))


def _label_matches(label: str | None, aliases: tuple[str, ...]) -> bool:
    if not label:
        return False
    norm = " ".join(str(label).strip().lower().replace("_", " ").replace("-", " ").split())
    if not norm:
        return False
    for alias in aliases:
        a = " ".join(alias.lower().split())
        if norm == a or a in norm or norm in a:
            return True
    return False


def _custom_field_by_label(raw: dict[str, Any], aliases: tuple[str, ...]) -> str | None:
    """Map Accurate charField*/customField* only when a companion label proves the meaning.

    Unlabeled charField noise must never invent Buffer/Urgent/Cetak/Ekspedisi.
    """
    for i in range(1, 21):
        label = _first_str(
            raw.get(f"charField{i}Name"),
            raw.get(f"charField{i}Label"),
            raw.get(f"charField{i}Title"),
            raw.get(f"customField{i}Name"),
            raw.get(f"customField{i}Label"),
            raw.get(f"dataClassification{i}Name"),
        )
        if not _label_matches(label, aliases):
            continue
        value = _first_str(
            raw.get(f"charField{i}"),
            raw.get(f"customField{i}"),
            raw.get(f"dataClassification{i}"),
        )
        if value:
            return value
    # Optional Accurate-style list of labeled custom fields.
    for key in ("customFieldList", "charFieldList", "dataClassificationList"):
        block = raw.get(key)
        if not isinstance(block, list):
            continue
        for entry in block:
            if not isinstance(entry, dict):
                continue
            label = _first_str(
                entry.get("name"),
                entry.get("label"),
                entry.get("title"),
                entry.get("fieldName"),
            )
            if not _label_matches(label, aliases):
                continue
            value = _first_str(
                entry.get("value"),
                entry.get("val"),
                entry.get("text"),
                entry.get("nameValue"),
            )
            if value:
                return value
    return None


def _expedition_from_shipment(raw: dict[str, Any]) -> str | None:
    """Step 135 — Pengiriman from Accurate Shipment Info `shipment.name` only.

    Live (PO/12/11/2026/000017): `shipment` is a dict with method `name` plus
    logistics keys (picName, picPhoneNumber, shipAddress, …). Owner UI
    Pengiriman = DIAMBIL matches `shipment.name`. Never treat PIC, address,
    or id as the Pengiriman method.
    """
    val = raw.get("shipment")
    if isinstance(val, str):
        text = val.strip()
        return text or None
    if isinstance(val, dict):
        name = val.get("name")
        if isinstance(name, str):
            text = name.strip()
            return text or None
    return None


_EXPEDITION_LABELS = (
    "ekspedisi",
    "expedition",
    "kurir",
    "courier",
    "shipping",
    "metode kirim",
    "cara kirim",
)
_ZONE_LABELS = (
    "zona",
    "zone",
    "zona pengiriman",
    "delivery zone",
    "wilayah kirim",
)
_BUFFER_LABELS = (
    "buffer",
    "buffer stock",
    "buffer/non-buffer",
    "buffer / non-buffer",
    "non-buffer",
)
_ORDER_STATUS_LABELS = (
    "status pesanan",
    "order priority",
    "prioritas",
    "urgent",
    "status urgent",
)
_PROCESS_LABELS = (
    "proses",
    "proses barang",
    "production process",
    "cetak",
    "jenis proses",
)
_COLOR_LABELS = (
    "warna",
    "warna barang",
    "color",
    "ink",
    "warna tinta",
)


def _parse_buffer_stock(value: str | None) -> bool | None:
    if value is None:
        return None
    norm = str(value).strip().lower().replace("_", " ").replace("-", " ")
    norm = " ".join(norm.split())
    if norm in {"buffer", "ya", "yes", "true", "1", "buffer stock"}:
        return True
    if norm in {
        "non buffer",
        "nonbuffer",
        "tidak",
        "no",
        "false",
        "0",
        "bukan buffer",
    }:
        return False
    return None


def _parse_urgent_state(value: str | None) -> str | None:
    if value is None:
        return None
    norm = str(value).strip().lower().replace("_", " ").replace("-", " ")
    norm = " ".join(norm.split())
    if norm in {"normal", "reguler", "regular", "standar"}:
        return "normal"
    if norm in {"urgent", "approved urgent", "legacy urgent", "ya", "yes", "true"}:
        return "approved_urgent"
    return None


def _sales_names_from_entity(
    entity: dict[str, Any],
) -> tuple[list[str], str | None]:
    """Collect official salesman names from one Accurate entity (header or line).

    Uses the same salesman* keys already proven in this gateway. Never reads
    createdUser / inputUser (creator ≠ Penjual).
    """
    for list_key in (
        "salesmanList",
        "salesPersonList",
        "salespersonList",
        "salesList",
    ):
        names = _sales_from_list(entity.get(list_key))
        if names:
            return names, list_key

    nested_keys = (
        ("salesPerson", "salesPerson"),
        ("salesperson", "salesperson"),
        ("salesman", "salesman"),
        ("sales", "sales"),
    )
    for key, source in nested_keys:
        nested = entity.get(key)
        if isinstance(nested, dict):
            name = _first_str(
                nested.get("name"),
                nested.get("fullName"),
                nested.get("salesmanName"),
                nested.get("salesPersonName"),
            )
            if name:
                return [name], source

    for key in (
        "salesPersonName",
        "salespersonName",
        "salesmanName",
        "salesName",
    ):
        name = _first_str(entity.get(key))
        if name:
            return [name], key

    scalar = entity.get("sales")
    if not isinstance(scalar, dict):
        name = _first_str(scalar)
        if name:
            return [name], "sales"
    return [], None


def _extract_sales(raw: dict[str, Any]) -> tuple[str | None, str | None]:
    """Official salesperson only — never confuse with document creator.

    Owner UI (Step 88/89): Penjual can sit on Sales Order item detail.
    Rule:
      1) Collect unique names from header salesman fields (existing).
      2) Then each detailItem line, same salesman keys, in line order.
      3) Join unique names with \", \" — never silently keep only the first line.
    Returns (joined_names, source_field).
    """
    ordered: list[str] = []
    sources: list[str] = []
    seen: set[str] = set()

    def _add(names: list[str], source: str | None) -> None:
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            ordered.append(name)
        if names and source and source not in sources:
            sources.append(source)

    header_names, header_source = _sales_names_from_entity(raw)
    _add(header_names, header_source)

    lines = raw.get("detailItem") or raw.get("detailItems") or raw.get("items") or []
    if isinstance(lines, list):
        for line in lines:
            if not isinstance(line, dict):
                continue
            line_names, line_source = _sales_names_from_entity(line)
            if not line_names:
                continue
            src = (
                f"detailItem.{line_source}" if line_source else "detailItem"
            )
            _add(line_names, src)

    if not ordered:
        return None, None
    return ", ".join(ordered), "+".join(sources) if sources else None


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


def _parse_qty(row: dict[str, Any]) -> tuple[float | None, bool]:
    """Parse line quantity with explicit verification.

    Returns ``(qty, verified)``:
    - Official zero → ``(0.0, True)``
    - Valid finite nonzero → ``(n, True)``
    - Missing / blank / invalid / NaN / Infinity → ``(None, False)``

    Never coerces unverified quantity into a verified zero.
    """
    if "quantity" in row:
        raw = row.get("quantity")
    elif "qty" in row:
        raw = row.get("qty")
    else:
        return None, False
    if raw is None:
        return None, False
    if isinstance(raw, str) and not raw.strip():
        return None, False
    try:
        num = float(raw)
    except (TypeError, ValueError):
        return None, False
    if not math.isfinite(num):
        return None, False
    return num, True


def _qty(row: dict[str, Any]) -> float | None:
    """Verified quantity or ``None`` when unverified (Slice 1M)."""
    qty, verified = _parse_qty(row)
    return qty if verified else None


def _normalize_process_token(raw: Any) -> str:
    """Map recognized process tokens → print|non_print; else unknown."""
    if raw is None:
        return "unknown"
    normalized = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    if normalized in {"print", "non_print"}:
        return normalized
    if normalized in {"cetak"}:
        return "print"
    if normalized in {
        "tidak_cetak",
        "noncetak",
        "non_cetak",
        "tidakcetak",
        "tidak_print",
        "non_print_item",
    }:
        return "non_print"
    return "unknown"


def _explicit_production_process(row: dict[str, Any]) -> str:
    """print|non_print from explicit field, Owner-approved slot, or labeled CF.

    Never infer from product name/category. Blank/unrecognized → unknown.
    Header slots never apply to line process (scope-isolated).
    """
    raw = row.get("production_process")
    if raw is None:
        raw = row.get("productionProcess")
    if raw is None:
        raw = approved_raw_value(
            row, scope="line", kind="production_process"
        )
    if raw is None:
        raw = _custom_field_by_label(row, _PROCESS_LABELS)
    return _normalize_process_token(raw)


def _line_color(row: dict[str, Any], item: dict[str, Any]) -> str | None:
    # Official Accurate color text — Owner-approved line charField2 when unlabeled.
    return _first_str(
        row.get("color"),
        row.get("warna"),
        row.get("detailColor"),
        item.get("color"),
        item.get("warna"),
        approved_raw_value(row, scope="line", kind="color"),
        _custom_field_by_label(row, _COLOR_LABELS),
        _custom_field_by_label(item, _COLOR_LABELS) if isinstance(item, dict) else None,
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
        qty, qty_verified = _parse_qty(row)
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
                "qty": qty,
                "qty_verified": qty_verified,
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
    # Buffer/Urgent: Owner-approved header slots, else labeled CF only.
    buffer_stock = _parse_buffer_stock(
        approved_raw_value(raw, scope="header", kind="buffer")
        or _custom_field_by_label(raw, _BUFFER_LABELS)
    )
    urgent_state = _parse_urgent_state(
        approved_raw_value(raw, scope="header", kind="order_priority")
        or _custom_field_by_label(raw, _ORDER_STATUS_LABELS)
    )
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
        # Step 137 — Pengiriman on list when Accurate returns shipment/native keys.
        # Detail enrich remains fallback when list omits shipment.
        "expedition": _first_str(
            raw.get("expedition"),
            raw.get("expeditionName"),
            raw.get("courier"),
            raw.get("courierName"),
            raw.get("shippingInfo"),
            raw.get("shippingMethod"),
            raw.get("shippingMethodName"),
            raw.get("deliveryMethod"),
            _expedition_from_shipment(raw),
            _custom_field_by_label(raw, _EXPEDITION_LABELS),
        ),
        # Nullable — unlabeled / missing stays null (never invent false).
        "buffer_stock": buffer_stock,
        "urgent_state": urgent_state,
    }


def normalize_sales_order(raw: dict[str, Any]) -> dict[str, Any]:
    base = normalize_sales_order_list_item(raw)
    lines = _lines(raw)
    base["line_items"] = lines
    base["line_count"] = len(lines)
    # Verified PO total only when every line quantity is verified (print + non-print).
    # Never invent total from unverified zeros; never multiply by ink/color count.
    if lines and all(bool(li.get("qty_verified")) for li in lines):
        base["total_quantity"] = sum(float(li["qty"]) for li in lines)
        base["total_quantity_verified"] = True
    else:
        base["total_quantity"] = None
        base["total_quantity_verified"] = False
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
        raw.get("courierName"),
        raw.get("shippingInfo"),
        raw.get("shippingMethod"),
        raw.get("shippingMethodName"),
        raw.get("deliveryMethod"),
        _expedition_from_shipment(raw),
        _custom_field_by_label(raw, _EXPEDITION_LABELS),
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
        raw.get("shipZone"),
        approved_raw_value(raw, scope="header", kind="delivery_zone"),
        _custom_field_by_label(raw, _ZONE_LABELS),
    )
    # Re-resolve Buffer/Urgent on full detail (Owner slots + labeled CF).
    buffer_stock = _parse_buffer_stock(
        approved_raw_value(raw, scope="header", kind="buffer")
        or _custom_field_by_label(raw, _BUFFER_LABELS)
    )
    urgent_state = _parse_urgent_state(
        approved_raw_value(raw, scope="header", kind="order_priority")
        or _custom_field_by_label(raw, _ORDER_STATUS_LABELS)
    )
    # Always set after detail resolve — None stays unknown (never invent false).
    base["buffer_stock"] = buffer_stock
    base["urgent_state"] = urgent_state
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
    so_id = None
    if isinstance(so_number, dict):
        so_id = _stable_int_id(so_number.get("id"))
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
    # Do not fall through from an explicit zero to another positive field.
    raw_amount = next((raw[k] for k in ("totalAmount", "amount", "paymentAmount")
                       if raw.get(k) is not None), "0")
    return {
        "id": _stable_int_id(raw.get("id")) or "",
        "number": str(raw.get("number") or raw.get("no") or raw.get("id") or ""),
        "status": status,
        "sales_order_number": str(so_number or ""),
        "sales_order_id": so_id,
        # Preserve the numeric public contract; exact decimal is additive.
        "amount": float(raw_amount),
        "amount_decimal": str(raw_amount),
        "currency": str(raw.get("currency") or raw.get("currencyCode") or "IDR"),
        "paid_at": raw.get("transDate") or raw.get("chequeDate") or raw.get("paidAt"),
        "customer": _party(customer),
        "branch": branch,
        "reversed": reversed_,
        "cancelled": cancelled,
        "verifiable": verifiable,
    }


def _stable_int_id(value: Any) -> str | None:
    """Canonical string id from Accurate integer/string ids. Reject bool/blank/garbage."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        value = int(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        s = value.strip()
        if not s or not s.lstrip("-").isdigit():
            return None
        return str(int(s))
    return None


def _parse_unit_ratio(row: dict[str, Any]) -> tuple[float | None, bool]:
    if "unitRatio" not in row and "unit_ratio" not in row:
        return None, False
    raw = row.get("unitRatio") if "unitRatio" in row else row.get("unit_ratio")
    if raw is None:
        return None, False
    if isinstance(raw, str) and not raw.strip():
        return None, False
    try:
        num = float(raw)
    except (TypeError, ValueError):
        return None, False
    if not math.isfinite(num):
        return None, False
    return num, True


def _sales_order_detail_nested_id(row: dict[str, Any]) -> str | None:
    nested = row.get("salesOrderDetail")
    if not isinstance(nested, dict):
        return None
    return _stable_int_id(nested.get("id"))


def normalize_delivery_note_line(row: dict[str, Any]) -> dict[str, Any]:
    """SJ detail line contract from Accurate delivery-order detailItem.

    Canonical (Owner-verified field names on Live DO detail):
      accurate_sj_line_id ← detailItem.id
      so_line_id          ← detailItem.salesOrderDetailId
      accurate_so_id      ← detailItem.salesOrderId
      accurate_item_id    ← detailItem.itemId
      quantity            ← detailItem.quantity
      unit_ratio          ← detailItem.unitRatio

    Legacy sku/qty/uom preserved for existing consumers.
    Never infer so_line_id from SKU, name, or array index.
    Never use salesOrderDetailId as the SJ line id.
    """
    item = row.get("item") if isinstance(row.get("item"), dict) else {}
    accurate_sj_line_id = _stable_int_id(row.get("id"))
    so_line_id = _stable_int_id(row.get("salesOrderDetailId"))
    nested_so_line_id = _sales_order_detail_nested_id(row)
    accurate_so_id = _stable_int_id(row.get("salesOrderId"))
    accurate_item_id = _stable_int_id(row.get("itemId") or item.get("id"))
    qty, qty_verified = _parse_qty(row)
    unit_ratio, unit_ratio_verified = _parse_unit_ratio(row)

    identity_conflicts: list[str] = []
    if (
        so_line_id is not None
        and nested_so_line_id is not None
        and so_line_id != nested_so_line_id
    ):
        identity_conflicts.append("salesOrderDetailId_ne_salesOrderDetail.id")
        # Fail closed: conflicting SO-line references are not authoritative.
        so_line_id = None

    line_identity_complete = bool(
        accurate_sj_line_id and so_line_id and qty_verified and qty is not None
    )
    uom = _uom(row, item)
    # Packing ledger is physical cups (PCS). Non-PCS / blank UOM cannot be
    # converted without guessing Accurate inventory base — fail closed.
    _PCS_UOM = frozenset({"PCS", "PC", "PIECE", "PIECES", "CUP", "CUPS"})
    uom_packing_compatible = str(uom or "").strip().upper() in _PCS_UOM
    # Loading must also have a verified unit ratio so qty×unitRatio can be
    # compared to packing physical cups without silent UOM drift.
    loading_eligible = bool(
        line_identity_complete
        and unit_ratio_verified
        and unit_ratio is not None
        and unit_ratio > 0
        and uom_packing_compatible
        and not identity_conflicts
    )

    return {
        # Legacy fields (preserved).
        "sku": str(
            row.get("itemNo") or item.get("no") or row.get("sku") or ""
        ),
        "qty": qty if qty is not None else 0,
        "uom": uom,
        # Canonical SJ↔SO line contract.
        "accurate_sj_line_id": accurate_sj_line_id,
        "so_line_id": so_line_id,
        "accurate_so_id": accurate_so_id,
        "accurate_item_id": accurate_item_id,
        "quantity": qty,
        "qty_verified": qty_verified,
        "unit_ratio": unit_ratio,
        "unit_ratio_verified": unit_ratio_verified,
        "uom_packing_compatible": uom_packing_compatible,
        "line_identity_complete": line_identity_complete,
        "loading_eligible": loading_eligible,
        "identity_conflicts": identity_conflicts,
        # Field semantics Owner-proven (CROSS_VERIFICATION=PASS on live DN/SO).
        # Per-request cross-GET remains optional defense; not claimed here.
        "so_line_id_source": "detailItem.salesOrderDetailId",
        "so_line_field_semantics_verified": True,
        "so_line_cross_verified": False,
    }


def normalize_delivery_note_lines(raw: dict[str, Any]) -> list[dict[str, Any]]:
    detail = raw.get("detailItem") or raw.get("detailItems") or raw.get("items") or []
    if not isinstance(detail, list):
        return []
    out: list[dict[str, Any]] = []
    for row in detail:
        if isinstance(row, dict):
            out.append(normalize_delivery_note_line(row))
    return out


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
    line_items = normalize_delivery_note_lines(raw)
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
        "line_items": line_items,
        "line_identity_complete": bool(line_items)
        and all(bool(li.get("line_identity_complete")) for li in line_items),
        "loading_eligible": bool(line_items)
        and all(bool(li.get("loading_eligible")) for li in line_items),
        "so_line_field_semantics_verified": True,
        "so_line_cross_verified": False,
    }
