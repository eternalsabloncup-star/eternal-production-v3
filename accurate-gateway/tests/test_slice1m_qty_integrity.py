"""Slice 1M: official zero vs missing/invalid qty; mixed print/non-print totals."""

from __future__ import annotations

import math

from app.contracts import so_detail
from app.custom_field_mapping import mapping_status, resolve_approved_slot
from app.normalize import _parse_qty, normalize_sales_order


def test_parse_qty_official_zero_vs_missing_invalid():
    assert _parse_qty({"quantity": 0}) == (0.0, True)
    assert _parse_qty({"quantity": "0"}) == (0.0, True)
    assert _parse_qty({}) == (None, False)
    assert _parse_qty({"quantity": None}) == (None, False)
    assert _parse_qty({"quantity": ""}) == (None, False)
    assert _parse_qty({"quantity": "abc"}) == (None, False)
    nan_qty, nan_ok = _parse_qty({"quantity": float("nan")})
    assert nan_ok is False and nan_qty is None
    inf_qty, inf_ok = _parse_qty({"quantity": float("inf")})
    assert inf_ok is False and inf_qty is None
    ninf_qty, ninf_ok = _parse_qty({"quantity": float("-inf")})
    assert ninf_ok is False and ninf_qty is None
    assert _parse_qty({"quantity": 1000}) == (1000.0, True)
    assert math.isfinite(1000.0)


def test_two_line_po_1000_plus_1000_includes_non_print():
    mapped = normalize_sales_order(
        {
            "id": 1,
            "number": "SO/SYN/QTY",
            "detailItem": [
                {
                    "id": 1,
                    "itemNo": "SYN-A",
                    "detailName": "A",
                    "quantity": 1000,
                    "production_process": "print",
                },
                {
                    "id": 2,
                    "itemNo": "SYN-B",
                    "detailName": "B",
                    "quantity": 1000,
                    "production_process": "non_print",
                },
            ],
        }
    )
    assert mapped["total_quantity"] == 2000.0
    assert mapped["total_quantity_verified"] is True
    assert mapped["line_count"] == 2
    assert all(li["qty_verified"] for li in mapped["line_items"])
    contract = so_detail(mapped)
    assert contract["total_quantity"] == 2000.0
    assert contract["total_quantity_verified"] is True
    assert contract["line_items"][0]["quantity"] == 1000.0
    assert contract["line_items"][1]["production_process"] == "non_print"


def test_missing_line_qty_blocks_verified_total():
    mapped = normalize_sales_order(
        {
            "id": 2,
            "number": "SO/SYN/MISS",
            "detailItem": [
                {"id": 1, "itemNo": "A", "quantity": 1000},
                {"id": 2, "itemNo": "B", "detailName": "noqty"},
            ],
        }
    )
    assert mapped["line_items"][0]["qty_verified"] is True
    assert mapped["line_items"][1]["qty"] is None
    assert mapped["line_items"][1]["qty_verified"] is False
    assert mapped["total_quantity"] is None
    assert mapped["total_quantity_verified"] is False
    contract = so_detail(mapped)
    assert contract["total_quantity"] is None
    assert contract["total_quantity_verified"] is False


def test_multicolor_does_not_multiply_physical_qty():
    # Two lines, not two colors of one line — physical sum stays 2000.
    mapped = normalize_sales_order(
        {
            "id": 3,
            "number": "SO/SYN/COLOR",
            "detailItem": [
                {
                    "id": 1,
                    "itemNo": "CUP",
                    "quantity": 1000,
                    "charField1Name": "Warna",
                    "charField1": "RED",
                    "production_process": "print",
                },
                {
                    "id": 2,
                    "itemNo": "LID",
                    "quantity": 1000,
                    "charField1Name": "Warna",
                    "charField1": "CLEAR",
                    "production_process": "non_print",
                },
            ],
        }
    )
    assert mapped["total_quantity"] == 2000.0
    assert mapped["line_items"][0]["color"] == "RED"


def test_unlabeled_charfield_process_stays_unknown():
    mapped = normalize_sales_order(
        {
            "id": 4,
            "number": "SO/SYN/UL",
            "charField3": "OUTLET",
            "detailItem": [
                {
                    "id": 1,
                    "itemNo": "X",
                    "quantity": 10,
                    "charField1": "Cetak",
                    "charField2": "RED",
                }
            ],
        }
    )
    assert mapped["expedition"] is None
    assert mapped["line_items"][0]["production_process"] == "unknown"
    assert mapped["line_items"][0]["color"] is None


def test_custom_field_mapping_foundation_blocked():
    st = mapping_status()
    assert st["status"] == "BLOCKED"
    assert st["approved_rule_count"] == 0
    assert resolve_approved_slot(scope="header", slot="charField3", companion_label=None) is None
    assert (
        resolve_approved_slot(
            scope="header", slot="charField3", companion_label="Ekspedisi"
        )
        is None
    )


def test_official_zero_line_keeps_verified_total():
    mapped = normalize_sales_order(
        {
            "id": 5,
            "number": "SO/SYN/ZERO",
            "detailItem": [
                {"id": 1, "itemNo": "A", "quantity": 0},
                {"id": 2, "itemNo": "B", "quantity": 5},
            ],
        }
    )
    assert mapped["line_items"][0]["qty"] == 0.0
    assert mapped["line_items"][0]["qty_verified"] is True
    assert mapped["total_quantity"] == 5.0
    assert mapped["total_quantity_verified"] is True
