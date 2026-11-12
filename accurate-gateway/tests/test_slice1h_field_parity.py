"""Slice 1H: labeled custom fields + nested salesmanList; unlabeled noise stays null/unknown."""

from app.normalize import normalize_sales_order, _extract_sales


def test_nested_salesman_list_object():
    name, source = _extract_sales(
        {
            "createdUserName": "TIANA",
            "salesmanList": [{"id": 9, "salesman": {"id": 3, "name": "Dimas Aji Prasetya"}}],
        }
    )
    assert name == "Dimas Aji Prasetya"
    assert source == "salesmanList"
    mapped = normalize_sales_order(
        {
            "id": 1,
            "number": "PO/TEST/1",
            "createdUserName": "TIANA",
            "salesmanList": [{"salesman": {"name": "Dimas Aji Prasetya"}}],
            "detailItem": [],
        }
    )
    assert mapped["sales"] == "Dimas Aji Prasetya"
    assert mapped["created_by_user"] == "TIANA"
    assert mapped["sales"] != mapped["created_by_user"]


def test_labeled_custom_fields_expedition_zone_buffer_status():
    mapped = normalize_sales_order(
        {
            "id": 2,
            "number": "PO/TEST/2",
            "charField1Name": "Ekspedisi",
            "charField1": "OUTLET",
            "charField2Name": "Zona Pengiriman",
            "charField2": "JU",
            "charField3Name": "Buffer / Non-Buffer",
            "charField3": "Non-Buffer",
            "charField4Name": "Status Pesanan",
            "charField4": "Normal",
            "detailItem": [],
        }
    )
    assert mapped["expedition"] == "OUTLET"
    assert mapped["delivery_zone"] == "JU"
    assert mapped["buffer_stock"] is False
    assert mapped["urgent_state"] == "normal"


def test_unlabeled_charfield_noise_stays_absent():
    mapped = normalize_sales_order(
        {
            "id": 3,
            "number": "PO/TEST/3",
            "charField1": "BUFFER",
            "charField2": "URGENT",
            "charField3": "OUTLET",
            "detailItem": [
                {
                    "id": 1,
                    "itemNo": "100003",
                    "detailName": "Cup",
                    "quantity": 1000,
                    "charField1": "PRINT",
                    "charField2": "HIJAU ARMY",
                }
            ],
        }
    )
    assert mapped["buffer_stock"] is None
    assert mapped["urgent_state"] is None
    assert mapped["expedition"] is None
    assert mapped["line_items"][0]["production_process"] == "unknown"
    assert mapped["line_items"][0]["color"] is None


def test_labeled_line_process_and_color_multi_item():
    mapped = normalize_sales_order(
        {
            "id": 4,
            "number": "PO/TEST/4",
            "detailItem": [
                {
                    "id": 11,
                    "itemNo": "100003",
                    "detailName": "Cup A",
                    "quantity": 1000,
                    "itemUnit": "pcs",
                    "charField1Name": "Proses",
                    "charField1": "Cetak",
                    "charField2Name": "Warna",
                    "charField2": "HIJAU ARMY",
                },
                {
                    "id": 12,
                    "itemNo": "100460",
                    "detailName": "Lid B",
                    "quantity": 1000,
                    "itemUnit": "pcs",
                    "charField1Name": "Proses Barang",
                    "charField1": "Tidak Cetak",
                    "charField2Name": "Warna Barang",
                    "charField2": "BENING",
                },
            ],
        }
    )
    lines = mapped["line_items"]
    assert len(lines) == 2
    assert mapped["total_quantity"] == 2000
    assert mapped["line_count"] == 2
    assert lines[0]["production_process"] == "print"
    assert lines[0]["color"] == "HIJAU ARMY"
    assert lines[1]["production_process"] == "non_print"
    assert lines[1]["color"] == "BENING"
