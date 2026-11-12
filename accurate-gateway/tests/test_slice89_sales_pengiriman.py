"""Step 89: Sales from item Penjual + Pengiriman/Ekspedisi evidence gates."""

from __future__ import annotations

from app.contracts import so_detail
from app.normalize import _extract_sales, normalize_sales_order


def test_sales_single_item_penjual_not_creator():
    mapped = so_detail(
        normalize_sales_order(
            {
                "id": 1,
                "number": "SO/SYN/89/S1",
                "createdUserName": "Admin Creator",
                "detailItem": [
                    {
                        "id": 10,
                        "itemNo": "A",
                        "quantity": 1,
                        "salesman": {"id": 3, "name": "Official Penjual"},
                    }
                ],
            }
        )
    )
    assert mapped["sales"] == "Official Penjual"
    assert mapped["sales_source"] == "detailItem.salesman"
    assert mapped["created_by_user"] == "Admin Creator"
    assert mapped["sales"] != mapped["created_by_user"]


def test_sales_multi_item_different_penjual_all_shown():
    name, source = _extract_sales(
        {
            "createdUserName": "Creator",
            "detailItem": [
                {"id": 1, "salesman": {"name": "Sales A"}},
                {"id": 2, "salesman": {"name": "Sales B"}},
                {"id": 3, "salesman": {"name": "Sales A"}},  # duplicate ignored
            ],
        }
    )
    assert name == "Sales A, Sales B"
    assert source == "detailItem.salesman"
    # Never silently first-only.
    assert "Sales B" in name


def test_sales_empty_stays_unknown_no_creator_fallback():
    mapped = normalize_sales_order(
        {
            "id": 2,
            "number": "SO/SYN/89/EMPTY",
            "createdUserName": "Admin Creator",
            "inputUserName": "Input User",
            "detailItem": [{"id": 1, "itemNo": "X", "quantity": 1}],
        }
    )
    assert mapped["sales"] is None
    assert mapped["sales_source"] is None
    assert mapped["created_by_user"] == "Admin Creator"


def test_header_salesman_plus_line_penjual_merged_unique():
    name, source = _extract_sales(
        {
            "salesmanList": [{"salesman": {"name": "Header Sales"}}],
            "detailItem": [
                {"salesman": {"name": "Line Sales"}},
                {"salesmanName": "Header Sales"},
            ],
        }
    )
    assert name == "Header Sales, Line Sales"
    assert "salesmanList" in (source or "")
    assert "detailItem" in (source or "")


def test_pengiriman_diambil_via_known_native_keys():
    """DIAMBIL via native expedition keys + Step 135 shipment.name."""
    for key in (
        "expedition",
        "expeditionName",
        "shippingMethodName",
        "deliveryMethod",
        "courierName",
    ):
        payload = {"id": 3, "number": "SO/SYN/89/SHIP", "detailItem": []}
        payload[key] = "DIAMBIL"
        mapped = normalize_sales_order(payload)
        assert mapped["expedition"] == "DIAMBIL", key
    # Step 135 Live: Shipment Info → shipment.name
    mapped = normalize_sales_order(
        {
            "id": 3,
            "number": "SO/SYN/89/SHIP2",
            "shipment": {"id": 1, "name": "DIAMBIL", "picName": "PIC"},
            "detailItem": [],
        }
    )
    assert mapped["expedition"] == "DIAMBIL"


def test_pengiriman_absent_stays_none_not_from_zone_or_branch():
    mapped = normalize_sales_order(
        {
            "id": 4,
            "number": "SO/SYN/89/NO-SHIP",
            "charField3": "JU",
            "branch": {"id": 50, "name": "Yogyakarta"},
            "toAddress": "Jl. Contoh",
            "fob": "Destination",
            "detailItem": [],
        }
    )
    assert mapped["expedition"] is None
    assert mapped["delivery_zone"] == "JU"


def test_unproven_shipment_keys_not_auto_mapped():
    # shipmentName / shipViaName remain unproven — only shipment.name is Live-proven.
    mapped = normalize_sales_order(
        {
            "id": 5,
            "number": "SO/SYN/89/CAND",
            "shipmentName": "DIAMBIL",
            "shipViaName": "DIAMBIL",
            "detailItem": [],
        }
    )
    assert mapped["expedition"] is None


def test_status_buffer_untouched_by_sales_pengiriman_work():
    mapped = normalize_sales_order(
        {
            "id": 6,
            "number": "SO/SYN/89/CF",
            "charField4": "Normal",
            "charField5": "Non - Buffer",
            "detailItem": [
                {"id": 1, "quantity": 1, "salesman": {"name": "Penjual X"}}
            ],
        }
    )
    assert mapped["urgent_state"] == "normal"
    assert mapped["buffer_stock"] is False
    assert mapped["sales"] == "Penjual X"
