"""Live-verified SJ contract (VPS GET /delivery-notes/120055).

Evidence: HTTP 200, source=accurate_live, live_verified=true, status=DIFAKTUR, line_count=1.
Lookup uses Accurate internal id; number remains business identity.
DIFAKTUR is not POD / terkirim.
"""

from __future__ import annotations

from app.normalize import normalize_delivery_note, normalize_sales_order


def _live_shaped_dn(**extra):
    raw = {
        "id": 120055,
        "number": "DO/2026/11/17/000019",
        "statusName": "DIFAKTUR",
        "customer": {
            "id": 57,
            "name": "KOPI MAJU 57",
            "mobilePhone": "+62 82134787254",
        },
        "branchName": "Cabang Gudang",
        "shipment": {"id": 3, "name": "OUTLET"},
        "shipDate": "2026-11-17",
        "printedTime": "2026-11-17 11:08:00",
        "printUserName": "anita",
        "deliveryZone": "SS",
        "description": "SABLON WARNA MERAH",
        "detailItem": [
            {
                "id": 27019,
                "salesOrderDetailId": 18019,
                "salesOrderId": 90019,
                "itemId": 100031,
                "itemNo": "100031",
                "quantity": 20000.0,
                "unitRatio": 1.0,
                "itemUnit": {"name": "PCS"},
            }
        ],
    }
    raw.update(extra)
    return raw


def test_live_120055_identity_and_print_vs_ship():
    note = normalize_delivery_note(_live_shaped_dn())
    assert note["accurate_id"] == "120055"
    assert note["id"] == "120055"
    assert note["number"] == "DO/2026/11/17/000019"
    assert note["status"] == "DIFAKTUR"
    assert note["line_count"] == 1
    assert note["sj_printed_at"] == "2026-11-17 11:08:00"
    assert note["print_user_name"] == "anita"
    assert note["shipped_at"] == "2026-11-17"
    assert note["sj_printed_at"] != note["shipped_at"]
    assert note["expedition"] == "OUTLET"
    assert note["customer_phone"] == "+62 82134787254"
    assert note["outlet"] is None
    assert note["outlet"] != note["expedition"]
    assert note["outlet"] != note["branch"]["name"]


def test_difaktur_is_not_pod_evidence():
    note = normalize_delivery_note(_live_shaped_dn())
    assert note["status"] == "DIFAKTUR"
    assert note["pod_evidence"] is False
    assert note["cancelled"] is False
    # Empty signature blocks remain unmapped
    assert note["warehouse_signer"] is None
    assert note["goods_checker"] is None
    assert note["courier_signer"] is None
    assert note["recipient_signer"] is None


def test_deliveryPrintedTime_alias():
    note = normalize_delivery_note(
        _live_shaped_dn(printedTime=None, deliveryPrintedTime="2026-11-17 12:00:00")
    )
    assert note["sj_printed_at"] == "2026-11-17 12:00:00"


def test_so_links_prefer_internal_sj_id_for_detail_lookup():
    so = normalize_sales_order(
        {
            "id": 90019,
            "number": "SO/X",
            "customerName": "C",
            "deliveryOrders": [
                {"id": 120055, "number": "DO/2026/11/17/000019"},
                {"number": "DO/ONLY-NUMBER"},
            ],
        }
    )
    links = so["links"]
    assert links["delivery_note_ids"][0] == "120055"
    assert links["delivery_note_numbers"][0] == "DO/2026/11/17/000019"
    assert "DO/ONLY-NUMBER" in links["delivery_note_ids"]
    assert links["sj_lookup_prefers_internal_id"] is True
