"""Deterministic fixture corpus for CI / local — not live Accurate evidence."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


FIXTURE_SALES_ORDERS: dict[str, dict[str, Any]] = {
    "SO-LIVE-001": {
        "id": "9001",
        "accurate_id": "9001",
        "number": "SO-LIVE-001",
        # Customer PO distinct from SO number — never fabricate.
        "po_number": "PO-CUST-001",
        "status": "OPEN",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "currency": "IDR",
        "total": 1500000,
        "line_items": [
            {
                "id": "8001",
                "accurate_line_id": "8001",
                "accurate_item_id": "6001",
                "sku": "BOX-A",
                "description": "Karton A cetak",
                "qty": 100,
                "quantity": 100,
                "qty_verified": True,
                "uom": "PCS",
                "unit_price": 15000,
                "production_process": "print",
            }
        ],
        "total_quantity": 100,
        "total_quantity_verified": True,
        "links": {
            "receipt_ids": ["RCP-OK-1"],
            "delivery_note_ids": ["SJ-OK-1"],
            "receipts_present": True,
            "delivery_notes_present": True,
            "evidence_authority": False,
        },
    },
    "SO-NONPRINT-001": {
        "id": "9101",
        "accurate_id": "9101",
        "number": "SO-NONPRINT-001",
        "po_number": "PO-NONPRINT-001",
        "status": "OPEN",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "currency": "IDR",
        "total": 500000,
        "line_items": [
            {
                "id": "8101",
                "accurate_line_id": "8101",
                "accurate_item_id": "6101",
                "sku": "STOCK-B",
                "description": "Stock non-cetak",
                "qty": 50,
                "quantity": 50,
                "qty_verified": True,
                "uom": "PCS",
                "unit_price": 10000,
                "production_process": "non_print",
            }
        ],
        "total_quantity": 50,
        "total_quantity_verified": True,
        "links": {
            "receipt_ids": ["RCP-OK-1"],
            "delivery_note_ids": [],
            "receipts_present": True,
            "delivery_notes_present": False,
            "evidence_authority": False,
        },
    },
    "SO-MIXED-001": {
        "id": "9102",
        "accurate_id": "9102",
        "number": "SO-MIXED-001",
        "po_number": "PO-MIXED-001",
        "status": "OPEN",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "currency": "IDR",
        "total": 2000000,
        "line_items": [
            {
                "id": "8201",
                "accurate_line_id": "8201",
                "accurate_item_id": "6201",
                "sku": "PRINT-C",
                "description": "Item cetak",
                "qty": 80,
                "quantity": 80,
                "qty_verified": True,
                "uom": "PCS",
                "unit_price": 20000,
                "production_process": "print",
            },
            {
                "id": "8202",
                "accurate_line_id": "8202",
                "accurate_item_id": "6202",
                "sku": "STOCK-D",
                "description": "Item non-cetak",
                "qty": 20,
                "quantity": 20,
                "qty_verified": True,
                "uom": "PCS",
                "unit_price": 5000,
                "production_process": "non_print",
            },
        ],
        "total_quantity": 100,
        "total_quantity_verified": True,
        "links": {
            "receipt_ids": ["RCP-OK-1"],
            "delivery_note_ids": [],
            "receipts_present": True,
            "delivery_notes_present": False,
            "evidence_authority": False,
        },
    },
    "SO-CANCELLED": {
        "id": "9002",
        "accurate_id": "9002",
        "number": "SO-CANCELLED",
        "po_number": None,
        "status": "CANCELLED",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "currency": "IDR",
        "total": 0,
        "line_items": [],
        "links": {
            "receipt_ids": [],
            "delivery_note_ids": [],
            "receipts_present": False,
            "delivery_notes_present": False,
            "evidence_authority": False,
        },
    },
}

FIXTURE_RECEIPTS: dict[str, dict[str, Any]] = {
    "RCP-OK-1": {
        "id": "RCP-OK-1",
        "number": "RCP-OK-1",
        "status": "POSTED",
        "sales_order_number": "SO-LIVE-001",
        "amount": 1500000,
        "currency": "IDR",
        "paid_at": "2026-03-20T10:00:00+07:00",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "reversed": False,
        "cancelled": False,
        "verifiable": True,
    },
    "RCP-CANCELLED": {
        "id": "RCP-CANCELLED",
        "number": "RCP-CANCELLED",
        "status": "CANCELLED",
        "sales_order_number": "SO-LIVE-001",
        "amount": 1500000,
        "currency": "IDR",
        "paid_at": "2026-03-20T10:00:00+07:00",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "reversed": False,
        "cancelled": True,
        "verifiable": False,
    },
    "RCP-REVERSED": {
        "id": "RCP-REVERSED",
        "number": "RCP-REVERSED",
        "status": "REVERSED",
        "sales_order_number": "SO-LIVE-001",
        "amount": 1500000,
        "currency": "IDR",
        "paid_at": "2026-03-20T10:00:00+07:00",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "reversed": True,
        "cancelled": False,
        "verifiable": False,
    },
    "RCP-MISMATCH": {
        "id": "RCP-MISMATCH",
        "number": "RCP-MISMATCH",
        "status": "POSTED",
        "sales_order_number": "SO-OTHER",
        "amount": 999,
        "currency": "IDR",
        "paid_at": "2026-03-20T10:00:00+07:00",
        "customer": {"id": "C-999", "name": "Wrong Customer"},
        "branch": {"id": "BR-SBY", "name": "Surabaya"},
        "reversed": False,
        "cancelled": False,
        "verifiable": True,
    },
}

FIXTURE_SALES_INVOICES: dict[str, dict[str, Any]] = {
    "INV-OPEN-1": {
        "id": "51001",
        "accurate_id": "51001",
        "number": "INV-OPEN-1",
        "status": "OPEN",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "invoice_total": "1000.00",
        "invoice_amount": "1000.00",
        "outstanding_amount": "1000.00",
        "remaining_amount": "1000.00",
        "paid_amount": "0.00",
        "financial_payment_status": "Belum Bayar",
        "owing_field_present": True,
        "verified": False,
        "source": "accurate_sales_invoice",
    },
    "INV-PARTIAL-1": {
        "id": "51002",
        "accurate_id": "51002",
        "number": "INV-PARTIAL-1",
        "status": "OPEN",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "invoice_total": "1000.00",
        "invoice_amount": "1000.00",
        "outstanding_amount": "400.00",
        "remaining_amount": "400.00",
        "paid_amount": "600.00",
        "financial_payment_status": "Sebagian",
        "owing_field_present": True,
        "verified": False,
        "source": "accurate_sales_invoice",
    },
    "INV-PAID-1": {
        "id": "51003",
        "accurate_id": "51003",
        "number": "INV-PAID-1",
        "status": "CLOSED",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "invoice_total": "1000.00",
        "invoice_amount": "1000.00",
        "outstanding_amount": "0.00",
        "remaining_amount": "0.00",
        "paid_amount": "1000.00",
        "financial_payment_status": "Lunas",
        "owing_field_present": True,
        "verified": False,
        "source": "accurate_sales_invoice",
    },
    "INV-UNKNOWN-1": {
        "id": "51004",
        "accurate_id": "51004",
        "number": "INV-UNKNOWN-1",
        "status": "OPEN",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "invoice_total": "1000.00",
        "invoice_amount": "1000.00",
        "outstanding_amount": None,
        "remaining_amount": None,
        "paid_amount": None,
        "financial_payment_status": None,
        "owing_field_present": False,
        "verified": False,
        "source": "accurate_sales_invoice",
    },
}

FIXTURE_DELIVERY_NOTES: dict[str, dict[str, Any]] = {
    "SJ-OK-1": {
        "id": "120001",
        "accurate_id": "120001",
        "number": "SJ-OK-1",
        "status": "DELIVERED",
        "sales_order_number": "SO-LIVE-001",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "shipped_at": "2026-03-21T09:00:00+07:00",
        "cancelled": False,
        "verifiable": True,
        "line_items": [
            {
                "sku": "BOX-A",
                "qty": 100,
                "uom": "PCS",
                "accurate_sj_line_id": "9001",
                "so_line_id": "8001",
                "accurate_so_id": "7001",
                "accurate_item_id": "6001",
                "quantity": 100.0,
                "qty_verified": True,
                "unit_ratio": 1.0,
                "unit_ratio_verified": True,
                "uom_packing_compatible": True,
                "line_identity_complete": True,
                "loading_eligible": True,
                "identity_conflicts": [],
                "so_line_id_source": "detailItem.salesOrderDetailId",
                "so_line_field_semantics_verified": True,
                "so_line_cross_verified": False,
            },
        ],
        "line_identity_complete": True,
        "loading_eligible": True,
        "so_line_field_semantics_verified": True,
        "so_line_cross_verified": False,
    },
    "SJ-CANCELLED": {
        "id": "120002",
        "accurate_id": "120002",
        "number": "SJ-CANCELLED",
        "status": "CANCELLED",
        "sales_order_number": "SO-LIVE-001",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "shipped_at": None,
        "cancelled": True,
        "verifiable": False,
        "line_items": [],
        "line_identity_complete": False,
        "loading_eligible": False,
        "so_line_field_semantics_verified": True,
        "so_line_cross_verified": False,
    },
    "SJ-MISMATCH": {
        "id": "120003",
        "accurate_id": "120003",
        "number": "SJ-MISMATCH",
        "status": "DELIVERED",
        "sales_order_number": "SO-OTHER",
        "customer": {"id": "C-999", "name": "Wrong Customer"},
        "branch": {"id": "BR-SBY", "name": "Surabaya"},
        "shipped_at": "2026-03-21T09:00:00+07:00",
        "cancelled": False,
        "verifiable": True,
        "line_items": [
            {
                "sku": "BOX-X",
                "qty": 1,
                "uom": "PCS",
                "accurate_sj_line_id": None,
                "so_line_id": None,
                "accurate_so_id": None,
                "accurate_item_id": None,
                "quantity": 1.0,
                "qty_verified": True,
                "unit_ratio": None,
                "unit_ratio_verified": False,
                "uom_packing_compatible": True,
                "line_identity_complete": False,
                "loading_eligible": False,
                "identity_conflicts": [],
                "so_line_id_source": "detailItem.salesOrderDetailId",
                "so_line_field_semantics_verified": True,
                "so_line_cross_verified": False,
            }
        ],
        "line_identity_complete": False,
        "loading_eligible": False,
        "so_line_field_semantics_verified": True,
        "so_line_cross_verified": False,
    },
}


def get_sales_order(number: str) -> dict[str, Any] | None:
    row = FIXTURE_SALES_ORDERS.get(number)
    return deepcopy(row) if row else None


def _perf_sales_orders() -> dict[str, dict[str, Any]]:
    """Deterministic 70-SO corpus for pagination / multi-user load (fixture only)."""
    out: dict[str, dict[str, Any]] = {}
    for i in range(1, 71):
        number = f"SO-P4-{i:03d}"
        out[number] = {
            "id": str(10000 + i),
            "accurate_id": str(10000 + i),
            "number": number,
            "po_number": None,
            "status": "OPEN",
            "customer": {"id": f"C-P4-{i:03d}", "name": f"Customer P4 {i:03d}"},
            "branch": {"id": "branch-a", "name": "Jakarta A"},
            "currency": "IDR",
            "total": 1000 * i,
            "line_items": [
                {
                    "sku": f"SKU-P4-{i:03d}",
                    "description": f"Item P4 {i:03d}",
                    "qty": 10 + i,
                    "uom": "PCS",
                    "unit_price": 1000,
                }
            ],
            "links": {"receipt_ids": [], "delivery_note_ids": []},
        }
    return out


# Merge static + perf corpus once.
FIXTURE_SALES_ORDERS.update(_perf_sales_orders())


def list_sales_orders(
    *,
    customer: str | None = None,
    branch: str | None = None,
    status: str | None = None,
    limit: int = 50,
    page: int = 1,
) -> tuple[list[dict[str, Any]], int]:
    rows = [deepcopy(v) for v in FIXTURE_SALES_ORDERS.values()]
    if customer:
        needle = customer.lower()
        rows = [
            r
            for r in rows
            if needle in str(r.get("customer", {}).get("name", "")).lower()
            or needle == str(r.get("customer", {}).get("id", "")).lower()
            or needle in str(r.get("number", "")).lower()
        ]
    if branch:
        needle = branch.lower()
        rows = [
            r
            for r in rows
            if needle in str(r.get("branch", {}).get("name", "")).lower()
            or needle == str(r.get("branch", {}).get("id", "")).lower()
        ]
    if status:
        rows = [r for r in rows if str(r.get("status", "")).upper() == status.upper()]
    rows.sort(key=lambda r: str(r.get("number") or ""))
    total = len(rows)
    page = max(1, page)
    size = max(1, min(limit, 200))
    start = (page - 1) * size
    return rows[start : start + size], total


def get_receipt(receipt_id: str) -> dict[str, Any] | None:
    row = FIXTURE_RECEIPTS.get(receipt_id)
    return deepcopy(row) if row else None


def get_delivery_note(dn_id: str) -> dict[str, Any] | None:
    key = (dn_id or "").strip()
    row = FIXTURE_DELIVERY_NOTES.get(key)
    if row is None:
        for candidate in FIXTURE_DELIVERY_NOTES.values():
            if str(candidate.get("accurate_id") or candidate.get("id") or "") == key:
                row = candidate
                break
            if str(candidate.get("number") or "") == key:
                row = candidate
                break
    return deepcopy(row) if row else None


def list_delivery_notes(
    *,
    keywords: str | None = None,
    branch: str | None = None,
    limit: int = 50,
    page: int = 1,
) -> tuple[list[dict[str, Any]], int]:
    rows = [deepcopy(v) for v in FIXTURE_DELIVERY_NOTES.values()]
    if keywords:
        needle = keywords.lower()
        rows = [
            r
            for r in rows
            if needle in str(r.get("number", "")).lower()
            or needle in str((r.get("customer") or {}).get("name", "")).lower()
        ]
    if branch:
        needle = branch.lower()
        rows = [
            r
            for r in rows
            if needle in str((r.get("branch") or {}).get("name", "")).lower()
            or needle == str((r.get("branch") or {}).get("id", "")).lower()
        ]
    rows.sort(key=lambda r: str(r.get("number") or ""))
    total = len(rows)
    page_n = max(1, page)
    size = max(1, min(limit, 200))
    start = (page_n - 1) * size
    return rows[start : start + size], total


def get_sales_invoice(invoice_id: str) -> dict[str, Any] | None:
    key = (invoice_id or "").strip()
    row = FIXTURE_SALES_INVOICES.get(key)
    if row is None:
        for candidate in FIXTURE_SALES_INVOICES.values():
            if str(candidate.get("accurate_id") or candidate.get("id") or "") == key:
                row = candidate
                break
            if str(candidate.get("number") or "") == key:
                row = candidate
                break
    return deepcopy(row) if row else None


def list_sales_invoices(
    *,
    keywords: str | None = None,
    outstanding_only: bool | None = None,
    limit: int = 50,
    page: int = 1,
) -> tuple[list[dict[str, Any]], int]:
    rows = [deepcopy(v) for v in FIXTURE_SALES_INVOICES.values()]
    if keywords:
        needle = keywords.lower()
        rows = [
            r
            for r in rows
            if needle in str(r.get("number", "")).lower()
            or needle in str((r.get("customer") or {}).get("name", "")).lower()
        ]
    if outstanding_only is True:
        rows = [
            r
            for r in rows
            if r.get("owing_field_present")
            and r.get("outstanding_amount") is not None
            and float(r["outstanding_amount"]) > 0
        ]
    elif outstanding_only is False:
        rows = [
            r
            for r in rows
            if r.get("owing_field_present")
            and r.get("outstanding_amount") is not None
            and float(r["outstanding_amount"]) <= 0
        ]
    rows.sort(key=lambda r: str(r.get("number") or ""))
    total = len(rows)
    page_n = max(1, page)
    size = max(1, min(limit, 200))
    start = (page_n - 1) * size
    return rows[start : start + size], total
