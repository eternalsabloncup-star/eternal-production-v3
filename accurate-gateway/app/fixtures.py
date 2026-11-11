"""Deterministic fixture corpus for CI / local — not live Accurate evidence."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


FIXTURE_SALES_ORDERS: dict[str, dict[str, Any]] = {
    "SO-LIVE-001": {
        "number": "SO-LIVE-001",
        "status": "OPEN",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "currency": "IDR",
        "total": 1500000,
        "line_items": [
            {
                "sku": "BOX-A",
                "description": "Karton A",
                "qty": 100,
                "uom": "PCS",
                "unit_price": 15000,
            }
        ],
        "links": {
            "receipt_ids": ["RCP-OK-1"],
            "delivery_note_ids": ["SJ-OK-1"],
        },
    },
    "SO-CANCELLED": {
        "number": "SO-CANCELLED",
        "status": "CANCELLED",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "currency": "IDR",
        "total": 0,
        "line_items": [],
        "links": {"receipt_ids": [], "delivery_note_ids": []},
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

FIXTURE_DELIVERY_NOTES: dict[str, dict[str, Any]] = {
    "SJ-OK-1": {
        "id": "SJ-OK-1",
        "number": "SJ-OK-1",
        "status": "DELIVERED",
        "sales_order_number": "SO-LIVE-001",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "shipped_at": "2026-03-21T09:00:00+07:00",
        "cancelled": False,
        "verifiable": True,
        "line_items": [
            {"sku": "BOX-A", "qty": 100, "uom": "PCS"},
        ],
    },
    "SJ-CANCELLED": {
        "id": "SJ-CANCELLED",
        "number": "SJ-CANCELLED",
        "status": "CANCELLED",
        "sales_order_number": "SO-LIVE-001",
        "customer": {"id": "C-100", "name": "PT Contoh"},
        "branch": {"id": "BR-JKT", "name": "Jakarta"},
        "shipped_at": None,
        "cancelled": True,
        "verifiable": False,
        "line_items": [],
    },
    "SJ-MISMATCH": {
        "id": "SJ-MISMATCH",
        "number": "SJ-MISMATCH",
        "status": "DELIVERED",
        "sales_order_number": "SO-OTHER",
        "customer": {"id": "C-999", "name": "Wrong Customer"},
        "branch": {"id": "BR-SBY", "name": "Surabaya"},
        "shipped_at": "2026-03-21T09:00:00+07:00",
        "cancelled": False,
        "verifiable": True,
        "line_items": [{"sku": "BOX-X", "qty": 1, "uom": "PCS"}],
    },
}


def get_sales_order(number: str) -> dict[str, Any] | None:
    row = FIXTURE_SALES_ORDERS.get(number)
    return deepcopy(row) if row else None


def list_sales_orders(
    *,
    customer: str | None = None,
    branch: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = [deepcopy(v) for v in FIXTURE_SALES_ORDERS.values()]
    if customer:
        needle = customer.lower()
        rows = [
            r
            for r in rows
            if needle in str(r.get("customer", {}).get("name", "")).lower()
            or needle == str(r.get("customer", {}).get("id", "")).lower()
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
    return rows[: max(1, min(limit, 200))]


def get_receipt(receipt_id: str) -> dict[str, Any] | None:
    row = FIXTURE_RECEIPTS.get(receipt_id)
    return deepcopy(row) if row else None


def get_delivery_note(dn_id: str) -> dict[str, Any] | None:
    row = FIXTURE_DELIVERY_NOTES.get(dn_id)
    return deepcopy(row) if row else None
