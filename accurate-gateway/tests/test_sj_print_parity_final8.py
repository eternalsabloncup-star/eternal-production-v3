"""Parity: Accurate SJ print (Direktur screenshot DO/2026/11/17/000019) ↔ normalize.

Print facts (no OCR as operational source — this fixture mirrors Owner-verified layout):
  Kepada phone · Ekspedisi=OUTLET · Tanggal SJ Dicetak · Tanggal Kirim ·
  line Outlet empty · Gudang/Cek/Kurir/Penerima signature lines empty.
"""

from __future__ import annotations

from app.normalize import normalize_delivery_note


def _screenshot_shaped_dn(**extra):
    raw = {
        "id": 190019,
        "number": "DO/2026/11/17/000019",
        "statusName": "POSTED",
        "customer": {
            "id": 57,
            "name": "KOPI MAJU 57",
            "mobilePhone": "+62 82134787254",
        },
        "branchName": "Cabang Gudang",
        "shipment": {"id": 3, "name": "OUTLET"},
        "shipDate": "2026-11-17",
        "printDate": "2026-11-17 11:08:00",
        "deliveryZone": "SS",
        "description": "SABLON WARNA MERAH",
        "detailItem": [
            {
                "id": 27019,
                "salesOrderDetailId": 18019,
                "salesOrderId": 90019,
                "itemId": 100031,
                "itemNo": "100031",
                "itemName": "12 oz Oval 7 gr Starindo",
                "quantity": 20000.0,
                "unitRatio": 1.0,
                "itemUnit": {"name": "PCS"},
                # Outlet per item blank on print
            }
        ],
    }
    raw.update(extra)
    return raw


def test_screenshot_parity_expedition_outlet_not_confused_with_outlet_column():
    note = normalize_delivery_note(_screenshot_shaped_dn())
    assert note["expedition"] == "OUTLET"
    # Header Outlet must NOT copy Ekspedisi or branch.name
    assert note["outlet"] is None
    assert note["branch"]["name"] == "Cabang Gudang"
    assert note["outlet"] != note["expedition"]
    assert note["outlet"] != note["branch"]["name"]
    # Item Outlet blank
    assert note["line_items"][0].get("outlet") is None


def test_screenshot_parity_phone_and_print_date_not_ship_date():
    note = normalize_delivery_note(_screenshot_shaped_dn())
    assert note["customer_phone"] == "+62 82134787254"
    assert note["sj_printed_at"] == "2026-11-17 11:08:00"
    assert note["shipped_at"] == "2026-11-17"
    assert note["sj_printed_at"] != note["shipped_at"]


def test_screenshot_parity_empty_signature_blocks_are_not_signers():
    note = normalize_delivery_note(_screenshot_shaped_dn())
    assert note["warehouse_signer"] is None
    assert note["goods_checker"] is None
    assert note["courier_signer"] is None
    assert note["recipient_signer"] is None


def test_item_outlet_pass_through_when_accurate_sends_line_outlet():
    note = normalize_delivery_note(
        _screenshot_shaped_dn(
            detailItem=[
                {
                    "id": 1,
                    "salesOrderDetailId": 2,
                    "salesOrderId": 3,
                    "itemId": 4,
                    "itemNo": "100031",
                    "quantity": 1,
                    "unitRatio": 1,
                    "outlet": "Outlet Semarang",
                }
            ]
        )
    )
    assert note["line_items"][0]["outlet"] == "Outlet Semarang"
    assert note["outlet"] is None  # header still empty
    assert note["expedition"] == "OUTLET"
