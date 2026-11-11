"""Slice 1E: Accurate SO detail parity fixture (AD MELIORA structure)."""

from __future__ import annotations

from app.contracts import so_detail
from app.normalize import normalize_sales_order, normalize_sales_order_list_item


AD_MELIORA_RAW = {
    "id": 990055,
    "number": "PO/11/11/2026/000005",
    "statusName": "OPEN",
    "transDate": "2026-11-11",
    "customer": {"id": 12, "name": "AD MELIORA COFFEE & EATERY"},
    "branch": {"id": 50, "name": "Yogyakarta"},
    "branchName": "Yogyakarta",
    "salesPersonName": "Sales Jogja Official",
    "createdUserName": "Admin Creator",
    "toAddress": "Jl. Contoh No. 1",
    "paymentTermName": "NET 30",
    "expedition": "Internal",
    "estimatedDeliveryDate": "2026-11-20",
    "deliveryZone": "Jogja Kota",
    "description": "Catatan PO uji",
    "detailItem": [
        {
            "id": 7001,
            "itemId": 100003,
            "itemNo": "100003",
            "detailName": "12 oz PET Datar 11 gr SJP",
            "quantity": "1000",
            "itemUnit": {"name": "PCS"},
            "color": "Hijau Army",
            "notes": "Cetak logo",
            "production_process": "print",
        },
        {
            "id": 7002,
            "itemId": 100460,
            "itemNo": "100460",
            "detailName": "LID PET Strawless Tam",
            "quantity": 1000,
            "itemUnit": "PCS",
            "color": "Bening",
            "production_process": "non_print",
        },
    ],
}


def test_ad_meliora_detail_lines_qty_and_mixed_process():
    mapped = so_detail(normalize_sales_order(AD_MELIORA_RAW))
    assert mapped["number"] == "PO/11/11/2026/000005"
    assert mapped["accurate_id"] == "990055"
    assert mapped["customer"] == "AD MELIORA COFFEE & EATERY"
    assert mapped["total_quantity"] == 2000.0
    assert mapped["line_count"] == 2
    assert mapped["sales"] == "Sales Jogja Official"
    assert mapped["created_by_user"] == "Admin Creator"
    assert mapped["sales"] != mapped["created_by_user"]
    assert mapped["branch_name"] == "Yogyakarta"
    assert mapped["branch_id"] == "50"
    assert mapped["address"] == "Jl. Contoh No. 1"
    assert mapped["payment_terms"] == "NET 30"
    assert mapped["expedition"] == "Internal"
    assert mapped["delivery_zone"] == "Jogja Kota"
    lines = mapped["line_items"]
    assert lines[0]["accurate_line_id"] == "7001"
    assert lines[0]["accurate_item_id"] == "100003"
    assert lines[0]["item_code"] == "100003"
    assert lines[0]["quantity"] == 1000.0
    assert lines[0]["unit"] == "PCS"
    assert lines[0]["production_process"] == "print"
    assert lines[0]["color"] == "Hijau Army"
    assert lines[1]["production_process"] == "non_print"
    assert lines[1]["color"] == "Bening"
    assert mapped["buffer_stock"] is None
    assert mapped["urgent_state"] is None


def test_blank_process_stays_unknown_not_print():
    raw = {
        "id": 1,
        "number": "SO-X",
        "statusName": "OPEN",
        "customer": {"id": 1, "name": "A"},
        "branch": {"id": 1, "name": "B"},
        "detailItem": [
            {
                "id": 9,
                "itemNo": "X",
                "detailName": "Cetak Box",
                "quantity": 10,
                "charField1": "PRINT",
            }
        ],
    }
    mapped = so_detail(normalize_sales_order(raw))
    assert mapped["line_items"][0]["production_process"] == "unknown"


def test_list_summary_has_no_fabricated_lines_or_qty():
    row = normalize_sales_order_list_item(
        {
            "id": 2,
            "number": "SO-LIST",
            "statusName": "OPEN",
            "customer": {"id": 1, "name": "A"},
            "branch": {"id": 50, "name": "Yogyakarta"},
            "salesPersonName": "Sales A",
            "totalAmount": 1,
        }
    )
    assert "line_items" not in row or row.get("line_items") in (None, [])
    assert row["sales"] == "Sales A"
    assert row["branch"]["name"] == "Yogyakarta"
    assert row["buffer_stock"] is None


def test_branch_id_not_guessed_as_name():
    mapped = so_detail(
        normalize_sales_order(
            {
                "id": 3,
                "number": "SO-BR",
                "statusName": "OPEN",
                "customer": {"id": 1, "name": "A"},
                "branchId": 150,
                "detailItem": [],
            }
        )
    )
    # Without branchName, name stays empty — UI must not invent Yogyakarta/Semarang.
    assert mapped["branch_id"] == "150"
    assert not mapped.get("branch_name")
