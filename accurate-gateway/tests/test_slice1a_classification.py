"""Slice 1A: Accurate line identity + nullable classifications (no heuristics)."""

from __future__ import annotations

from app.contracts import so_detail, so_list_row
from app.normalize import normalize_sales_order, normalize_sales_order_list_item


def test_detail_item_id_survives_normalize_and_contract():
    detail = normalize_sales_order(
        {
            "id": 823001,
            "number": "SO/EP/100",
            "statusName": "OPEN",
            "customer": {"id": 1, "name": "A"},
            "branch": {"id": 2, "name": "JKT"},
            "detailItem": [
                {
                    "id": 556677,
                    "itemId": 88,
                    "itemNo": "SKU-1",
                    "detailName": "Sticker",
                    "quantity": 100,
                    "itemUnit": "pcs",
                }
            ],
        }
    )
    mapped = so_detail(detail)
    line = mapped["line_items"][0]
    assert line["accurate_line_id"] == "556677"
    assert line["accurate_item_id"] == "88"
    assert line["production_process"] == "unknown"


def test_unknown_classifications_stay_null_or_unknown_after_sync_shape():
    row = normalize_sales_order_list_item(
        {
            "id": 1,
            "number": "SO-1",
            "statusName": "OPEN",
            "customer": {"id": 1, "name": "A"},
            "branch": {"id": 1, "name": "B"},
            "totalAmount": 1,
            # charField noise must not invent Buffer/Urgent
            "charField1": "BUFFER",
            "charField2": "URGENT",
            "numericField1": 1,
        }
    )
    out = so_list_row(row)
    assert out["buffer_stock"] is None
    assert out["urgent_state"] is None


def test_no_false_production_from_product_name_alone():
    # Product name / item flags must never invent print; Owner slot still maps when present.
    detail = normalize_sales_order(
        {
            "id": 2,
            "number": "SO-2",
            "statusName": "OPEN",
            "customer": {"id": 1, "name": "A"},
            "branch": {"id": 1, "name": "B"},
            "detailItem": [
                {
                    "id": 10,
                    "itemId": 1,
                    "itemNo": "P-1",
                    "detailName": "Cetak Box",
                    "quantity": 5,
                    "numericField1": 1,
                    "item": {"name": "Print Item", "isSold": True},
                }
            ],
        }
    )
    mapped = so_detail(detail)
    assert mapped["line_items"][0]["production_process"] == "unknown"
    assert mapped["buffer_stock"] is None
    assert mapped["urgent_state"] is None


def test_owner_slot_charfield1_maps_print_token():
    detail = normalize_sales_order(
        {
            "id": 22,
            "number": "SO-2B",
            "statusName": "OPEN",
            "customer": {"id": 1, "name": "A"},
            "branch": {"id": 1, "name": "B"},
            "detailItem": [
                {
                    "id": 10,
                    "itemNo": "P-1",
                    "detailName": "Cup",
                    "quantity": 5,
                    "charField1": "PRINT",
                }
            ],
        }
    )
    assert so_detail(detail)["line_items"][0]["production_process"] == "print"


def test_mixed_print_non_print_lines_representable():
    detail = normalize_sales_order(
        {
            "id": 3,
            "number": "SO-MIX",
            "statusName": "OPEN",
            "customer": {"id": 1, "name": "A"},
            "branch": {"id": 1, "name": "B"},
            "detailItem": [
                {
                    "id": 101,
                    "itemId": 1,
                    "quantity": 10,
                    "production_process": "print",
                },
                {
                    "id": 102,
                    "itemId": 2,
                    "quantity": 20,
                    "production_process": "non_print",
                },
                {
                    "id": 103,
                    "itemId": 3,
                    "quantity": 30,
                },
            ],
        }
    )
    mapped = so_detail(detail)
    processes = [li["production_process"] for li in mapped["line_items"]]
    ids = [li["accurate_line_id"] for li in mapped["line_items"]]
    assert processes == ["print", "non_print", "unknown"]
    assert ids == ["101", "102", "103"]


def test_explicit_production_process_only_accepts_print_non_print():
    detail = normalize_sales_order(
        {
            "id": 4,
            "number": "SO-4",
            "statusName": "OPEN",
            "customer": {"id": 1, "name": "A"},
            "branch": {"id": 1, "name": "B"},
            "detailItem": [
                {"id": 1, "quantity": 1, "production_process": "PRINT"},
                {"id": 2, "quantity": 1, "production_process": "maybe"},
            ],
        }
    )
    mapped = so_detail(detail)
    assert mapped["line_items"][0]["production_process"] == "print"
    assert mapped["line_items"][1]["production_process"] == "unknown"
