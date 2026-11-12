"""Step 87: Sales / Expedition / Urgent(CF4) / Buffer(CF5) — verified sources only."""

from __future__ import annotations

import inspect

from app import accurate_client
from app.normalize import (
    _extract_sales,
    _parse_buffer_stock,
    _parse_urgent_state,
    normalize_sales_order,
    normalize_sales_order_list_item,
)


def test_list_fields_request_includes_owner_header_cf_slots():
    src = inspect.getsource(accurate_client.AccurateClient.list_sales_orders)
    assert "charField4" in src and "charField5" in src and "charField3" in src
    assert "salesmanList" in src
    # Step 137 — shipment for Pengiriman on list when Accurate returns it.
    assert "shipment" in src
    # Expedition has no Owner ordinal — do not auto-request charField1/2/6 as expedition.
    assert "charField1" not in src
    assert "charField2" not in src
    assert "charField6" not in src


def test_list_item_cf4_cf5_map_without_companion_labels():
    row = normalize_sales_order_list_item(
        {
            "id": 11,
            "number": "SO/SYN/87/LIST",
            "charField4": "Urgent",
            "charField5": "Buffer",
            "createdUserName": "Creator Must Not Be Sales",
        }
    )
    assert row["urgent_state"] == "approved_urgent"
    assert row["buffer_stock"] is True
    assert row["sales"] is None
    assert row["sales_source"] is None


def test_list_item_unknown_tokens_stay_null_not_normal():
    row = normalize_sales_order_list_item(
        {
            "id": 12,
            "number": "SO/SYN/87/UNK",
            "charField4": "Maybe",
            "charField5": "Maybe",
        }
    )
    assert row["urgent_state"] is None
    assert row["buffer_stock"] is None


def test_urgent_token_classification():
    assert _parse_urgent_state("Normal") == "normal"
    assert _parse_urgent_state("Urgent") == "approved_urgent"
    assert _parse_urgent_state("") is None
    assert _parse_urgent_state("xyz") is None


def test_buffer_token_classification():
    assert _parse_buffer_stock("Buffer") is True
    assert _parse_buffer_stock("Non-Buffer") is False
    assert _parse_buffer_stock("Non Buffer") is False
    assert _parse_buffer_stock("") is None
    assert _parse_buffer_stock("xyz") is None


def test_sales_official_salesman_list_not_creator():
    name, source = _extract_sales(
        {
            "createdUserName": "Admin Creator",
            "salesmanList": [{"salesman": {"name": "Official Sales"}}],
        }
    )
    assert name == "Official Sales"
    assert source == "salesmanList"
    mapped = normalize_sales_order(
        {
            "id": 1,
            "number": "SO/SYN/87/SALES",
            "createdUserName": "Admin Creator",
            "detailItem": [],
        }
    )
    assert mapped["sales"] is None
    assert mapped["created_by_user"] == "Admin Creator"


def test_expedition_blocked_without_native_or_labeled_cf():
    mapped = normalize_sales_order(
        {
            "id": 2,
            "number": "SO/SYN/87/EXP",
            # Owner CF3/4/5 occupied — do not invent expedition from these.
            "charField3": "JU",
            "charField4": "Normal",
            "charField5": "Non-Buffer",
            "charField1": "JNE-GUESS",
            "detailItem": [],
        }
    )
    assert mapped["expedition"] is None
    assert mapped["urgent_state"] == "normal"
    assert mapped["buffer_stock"] is False


def test_labeled_expedition_still_works_when_companion_label_proves_slot():
    """Label-proven CF remains the only verified expedition path (no Owner ordinal)."""
    mapped = normalize_sales_order(
        {
            "id": 3,
            "number": "SO/SYN/87/EXP-LAB",
            "charField6Name": "Ekspedisi",
            "charField6": "OUTLET",
            "charField4": "Normal",
            "charField5": "Buffer",
            "detailItem": [],
        }
    )
    assert mapped["expedition"] == "OUTLET"
    assert mapped["urgent_state"] == "normal"
    assert mapped["buffer_stock"] is True
