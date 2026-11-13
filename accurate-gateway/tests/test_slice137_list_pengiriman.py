"""Step 137 — list carries shipment.name Pengiriman; null when absent."""

from __future__ import annotations

import inspect

from app import accurate_client
from app.contracts import so_detail, so_list_row
from app.normalize import normalize_sales_order, normalize_sales_order_list_item


def test_list_fields_request_includes_shipment():
    src = inspect.getsource(accurate_client.AccurateClient.list_sales_orders)
    assert "shipment" in src
    assert "charField4" in src and "charField5" in src
    # LIVE GATE (Step 139): Accurate list.do accepting nested shipment in fields=
    # is not proven offline — see docs/slice137-pengiriman-list-live-gate.md.
    assert "detail enrich remains fallback" in src


def test_list_item_shipment_name_maps_pengiriman():
    row = normalize_sales_order_list_item(
        {
            "id": 137,
            "number": "SO/SYN/137/LIST",
            "shipment": {
                "id": 9,
                "name": "DIAMBIL",
                "picName": "PIC",
                "shipAddress": "Alamat",
            },
            "charField4": "Normal",
            "charField5": "Non - Buffer",
            "createdUserName": "Creator",
            "detailItem": [
                {"salesmanList": [{"salesman": {"name": "Penjual"}}]},
            ],
        }
    )
    assert row["expedition"] == "DIAMBIL"
    assert row["urgent_state"] == "normal"
    assert row["buffer_stock"] is False
    assert row["sales"] == "Penjual"
    contract = so_list_row(row)
    assert contract["expedition"] == "DIAMBIL"


def test_list_without_shipment_stays_none():
    row = normalize_sales_order_list_item(
        {
            "id": 138,
            "number": "SO/SYN/137/NONE",
            "charField4": "Urgent",
            "charField5": "Buffer",
            "detailItem": [],
        }
    )
    assert row["expedition"] is None
    assert so_list_row(row)["expedition"] is None
    assert row["urgent_state"] == "approved_urgent"
    assert row["buffer_stock"] is True


def test_detail_still_maps_when_list_omitted_shipment_only_on_detail_shape():
    mapped = so_detail(
        normalize_sales_order(
            {
                "id": 139,
                "number": "SO/SYN/137/DET",
                "shipment": {"name": "DIAMBIL"},
                "charField4": "Normal",
                "charField5": "Non-Buffer",
                "detailItem": [{"quantity": 1, "salesmanName": "Penjual"}],
            }
        )
    )
    assert mapped["expedition"] == "DIAMBIL"
    assert mapped["sales"] == "Penjual"
    assert mapped["urgent_state"] == "normal"
    assert mapped["buffer_stock"] is False
