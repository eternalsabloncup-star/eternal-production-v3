"""Slice 1N: Owner-approved Accurate charField mapping (header vs item scopes)."""

from __future__ import annotations

import pytest

from app.contracts import so_detail
from app.custom_field_mapping import (
    APPROVED_RULES,
    MAPPING_STATUS,
    approved_raw_value,
    mapping_status,
    resolve_approved_slot,
)
from app.normalize import normalize_sales_order


OWNER_PO_RAW = {
    "id": 990055,
    "number": "SO/SYN/1N/OWNER",
    "statusName": "OPEN",
    "transDate": "2026-11-11",
    "customer": {"id": 1, "name": "Synthetic Customer"},
    "branch": {"id": 50, "name": "Yogyakarta"},
    "createdUserName": "Admin Creator",
    # Header Owner ordinals (labels omitted — mirrors Live Step 48).
    "charField3": "JU",
    "charField4": "Normal",
    "charField5": "Non-Buffer",
    # charField1/2 on header must NOT leak into line process/color.
    "charField1": "IGNORE-HEADER-PROCESS",
    "charField2": "IGNORE-HEADER-COLOR",
    "detailItem": [
        {
            "id": 7001,
            "itemNo": "SYN-PRINT",
            "detailName": "Cup Print",
            "quantity": 1000,
            "itemUnit": "PCS",
            "charField1": "Cetak",
            "charField2": "HIJAU ARMY",
        },
        {
            "id": 7002,
            "itemNo": "SYN-LID",
            "detailName": "Lid Non Print",
            "quantity": 1000,
            "itemUnit": "PCS",
            "charField1": "Tidak Cetak",
            "charField2": "BENING",
        },
    ],
}


def test_mapping_status_partial_five_owner_rules():
    st = mapping_status()
    assert st["status"] == "PARTIAL"
    assert st["approved_rule_count"] == 5
    assert MAPPING_STATUS == "PARTIAL"
    assert len(APPROVED_RULES) == 5
    assert "expedition" not in st["active_kinds"]
    assert "sales" in st["blocked_kinds"]


def test_resolve_owner_slots_without_companion_labels():
    assert (
        resolve_approved_slot(scope="header", slot="charField3", companion_label=None)
        == "delivery_zone"
    )
    assert (
        resolve_approved_slot(scope="header", slot="charField4") == "order_priority"
    )
    assert resolve_approved_slot(scope="header", slot="charField5") == "buffer"
    assert (
        resolve_approved_slot(scope="line", slot="charField1") == "production_process"
    )
    assert resolve_approved_slot(scope="line", slot="charField2") == "color"
    # No expedition rule.
    assert resolve_approved_slot(scope="header", slot="charField1") is None
    assert resolve_approved_slot(scope="header", slot="charField2") is None


def test_conflicting_companion_label_rejects_slot():
    assert (
        resolve_approved_slot(
            scope="header",
            slot="charField3",
            companion_label="Ekspedisi",
        )
        is None
    )


def test_owner_po_maps_zone_status_buffer_process_color_qty():
    mapped = so_detail(normalize_sales_order(OWNER_PO_RAW))
    assert mapped["total_quantity"] == 2000.0
    assert mapped["total_quantity_verified"] is True
    assert mapped["line_count"] == 2
    assert mapped["delivery_zone"] == "JU"
    assert mapped["urgent_state"] == "normal"
    assert mapped["buffer_stock"] is False
    # Expedition still blocked — no native/label/approved expedition.
    assert mapped["expedition"] is None
    # Sales absent — never creator.
    assert mapped["sales"] is None
    assert mapped["created_by_user"] == "Admin Creator"
    lines = mapped["line_items"]
    assert lines[0]["production_process"] == "print"
    assert lines[0]["color"] == "HIJAU ARMY"
    assert lines[0]["quantity"] == 1000.0
    assert lines[1]["production_process"] == "non_print"
    assert lines[1]["color"] == "BENING"
    assert lines[1]["quantity"] == 1000.0


def test_header_item_scope_isolation():
    mapped = normalize_sales_order(OWNER_PO_RAW)
    # Header noise on charField1/2 must not become line fields.
    assert mapped["line_items"][0]["production_process"] != "IGNORE-HEADER-PROCESS"
    assert mapped["line_items"][0]["color"] != "IGNORE-HEADER-COLOR"
    # Line process must not come from header approved zone slot.
    assert approved_raw_value(
        OWNER_PO_RAW, scope="header", kind="production_process"
    ) is None


def test_normal_not_urgent_non_buffer_not_buffer():
    mapped = normalize_sales_order(
        {
            "id": 1,
            "number": "SO/SYN/FLAGS",
            "charField4": "Normal",
            "charField5": "Non-Buffer",
            "detailItem": [{"id": 1, "quantity": 1, "charField1": "Cetak"}],
        }
    )
    assert mapped["urgent_state"] == "normal"
    assert mapped["buffer_stock"] is False


def test_unknown_process_and_empty_color_stay_unknown():
    mapped = normalize_sales_order(
        {
            "id": 2,
            "number": "SO/SYN/UNK",
            "detailItem": [
                {
                    "id": 1,
                    "quantity": 10,
                    "charField1": "Maybe Later",
                    "charField2": "",
                }
            ],
        }
    )
    assert mapped["line_items"][0]["production_process"] == "unknown"
    assert mapped["line_items"][0]["color"] is None


def test_urgent_and_buffer_explicit_values():
    mapped = normalize_sales_order(
        {
            "id": 3,
            "number": "SO/SYN/URG",
            "charField4": "Urgent",
            "charField5": "Buffer",
            "detailItem": [],
        }
    )
    assert mapped["urgent_state"] == "approved_urgent"
    assert mapped["buffer_stock"] is True


def test_colors_not_swapped_across_lines():
    mapped = normalize_sales_order(OWNER_PO_RAW)
    assert mapped["line_items"][0]["color"] == "HIJAU ARMY"
    assert mapped["line_items"][1]["color"] == "BENING"


def test_duplicate_rules_rejected():
    from app import custom_field_mapping as m

    with pytest.raises(ValueError, match="duplicate|conflict"):
        m._validate_approved_rules(
            m.APPROVED_RULES
            + (
                m.CustomFieldMappingRule(
                    scope="header",
                    slot="charField3",
                    kind="delivery_zone",
                    label_aliases=("zona",),
                    provenance="dup",
                ),
            )
        )
