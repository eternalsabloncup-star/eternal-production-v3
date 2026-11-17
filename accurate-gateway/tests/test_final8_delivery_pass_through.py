"""Final-8 Delivery vs Accurate SJ semantics (Direktur print).

Ekspedisi OUTLET ≠ Outlet column. shipped_at ≠ Tanggal SJ Dicetak.
Empty signature blocks ≠ signer evidence.
"""

from __future__ import annotations

from app.normalize import normalize_delivery_note

FINAL8_CLASSIFICATION = {
    "customer_phone": "MAP_IF_API",  # verified customer contact only
    "outlet": "NEEDS_SOURCE",  # not expedition; not branch.name
    "sj_printed_at": "MAP_IF_API",  # printDate* only
    "item_outlets": "MAP_IF_API",  # detailItem.outlet
    "warehouse_signer": "NEEDS_SOURCE",  # empty print block ≠ signature
    "goods_checker": "NEEDS_SOURCE",
    "courier_signer": "NEEDS_SOURCE",
    "recipient_signer": "NEEDS_SOURCE",
}


def test_final8_classification_keys():
    assert set(FINAL8_CLASSIFICATION) == {
        "customer_phone",
        "outlet",
        "sj_printed_at",
        "item_outlets",
        "warehouse_signer",
        "goods_checker",
        "courier_signer",
        "recipient_signer",
    }


def test_branch_and_expedition_do_not_fill_outlet():
    note = normalize_delivery_note(
        {
            "id": 1,
            "number": "DO/X",
            "customerName": "Cust",
            "branchName": "Cabang A",
            "shipment": {"name": "OUTLET"},
            "shipDate": "2026-11-17",
            "detailItem": [
                {
                    "id": 1,
                    "salesOrderDetailId": 2,
                    "salesOrderId": 3,
                    "itemId": 4,
                    "quantity": 1,
                    "unitRatio": 1,
                }
            ],
        }
    )
    assert note["expedition"] == "OUTLET"
    assert note["outlet"] is None
    assert note["sj_printed_at"] is None
    assert note["customer_phone"] is None


def test_explicit_print_phone_line_outlet_pass_through():
    note = normalize_delivery_note(
        {
            "id": 2,
            "number": "DO/Y",
            "customer": {"id": "C1", "name": "Cust", "mobilePhone": "081234"},
            "printDate": "2026-11-17T11:08:00",
            "outlet": "Outlet Header",
            "shipment": {"name": "OUTLET"},
            "detailItem": [
                {
                    "id": 1,
                    "salesOrderDetailId": 2,
                    "salesOrderId": 3,
                    "itemId": 4,
                    "quantity": 1,
                    "unitRatio": 1,
                    "outlet": "Outlet Line",
                }
            ],
        }
    )
    assert note["customer_phone"] == "081234"
    assert note["sj_printed_at"] == "2026-11-17T11:08:00"
    assert note["outlet"] == "Outlet Header"
    assert note["expedition"] == "OUTLET"
    assert note["line_items"][0]["outlet"] == "Outlet Line"
