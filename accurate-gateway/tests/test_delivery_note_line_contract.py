"""SJ delivery-note line identity contract (Accurate DO detailItem).

Live Owner evidence (SJ DO/2026/11/12/000027) proved field *presence*:
  detailItem.id, salesOrderDetailId, salesOrderId, itemId, quantity, unitRatio.
Cross-GET proof that salesOrderDetailId == SO detailItem.id remains PARTIAL.
"""

from __future__ import annotations

from app.normalize import (
    normalize_delivery_note,
    normalize_delivery_note_line,
)


def _raw_line(**overrides):
    base = {
        "id": 27001,
        "salesOrderDetailId": 18001,
        "salesOrderId": 90001,
        "itemId": 5001,
        "itemNo": "CUP-22",
        "quantity": 4000.0,
        "unitRatio": 1.0,
        "itemUnit": {"name": "PCS"},
        "salesOrderDetail": {"id": 18001},
    }
    base.update(overrides)
    return base


def test_canonical_mapping_from_verified_field_names():
    line = normalize_delivery_note_line(_raw_line())
    assert line["accurate_sj_line_id"] == "27001"
    assert line["so_line_id"] == "18001"
    assert line["accurate_so_id"] == "90001"
    assert line["accurate_item_id"] == "5001"
    assert line["quantity"] == 4000.0
    assert line["qty"] == 4000.0  # legacy alias preserved
    assert line["unit_ratio"] == 1.0
    assert line["sku"] == "CUP-22"
    assert line["uom"] == "PCS"
    assert line["line_identity_complete"] is True
    assert line["loading_eligible"] is True
    assert line["so_line_field_semantics_verified"] is True
    assert line["so_line_cross_verified"] is False
    assert line["identity_conflicts"] == []


def test_never_uses_sales_order_detail_id_as_sj_line_id():
    line = normalize_delivery_note_line(
        _raw_line(id=None, salesOrderDetailId=18001)
    )
    assert line["accurate_sj_line_id"] is None
    assert line["so_line_id"] == "18001"
    assert line["line_identity_complete"] is False


def test_absent_so_line_id_incomplete():
    line = normalize_delivery_note_line(_raw_line(salesOrderDetailId=None))
    assert line["so_line_id"] is None
    assert line["line_identity_complete"] is False


def test_null_ids_incomplete():
    line = normalize_delivery_note_line(
        _raw_line(id=None, salesOrderDetailId=None, salesOrderId=None, itemId=None)
    )
    assert line["accurate_sj_line_id"] is None
    assert line["so_line_id"] is None
    assert line["line_identity_complete"] is False


def test_malformed_ids_rejected():
    line = normalize_delivery_note_line(
        _raw_line(
            id="not-an-id",
            salesOrderDetailId="",
            salesOrderId=12.5,
            itemId=True,  # bool must not coerce to 1
        )
    )
    assert line["accurate_sj_line_id"] is None
    assert line["so_line_id"] is None
    assert line["accurate_so_id"] is None
    assert line["accurate_item_id"] is None
    assert line["line_identity_complete"] is False


def test_conflicting_nested_sales_order_detail_fail_closed():
    line = normalize_delivery_note_line(
        _raw_line(
            salesOrderDetailId=18001,
            salesOrderDetail={"id": 18999},
        )
    )
    assert line["so_line_id"] is None
    assert "salesOrderDetailId_ne_salesOrderDetail.id" in line["identity_conflicts"]
    assert line["line_identity_complete"] is False


def test_sku_alone_never_completes_identity():
    line = normalize_delivery_note_line(
        {
            "itemNo": "BOX-A",
            "quantity": 100,
            "itemUnit": "PCS",
        }
    )
    assert line["sku"] == "BOX-A"
    assert line["line_identity_complete"] is False
    assert line["so_line_id"] is None
    assert line["accurate_sj_line_id"] is None


def test_document_level_flags_and_legacy_fields():
    raw = {
        "id": 27,
        "number": "DO/2026/11/12/000027",
        "statusName": "DELIVERED",
        "salesOrderNumber": "SO/2026/11/01/000010",
        "customer": {"id": 1, "name": "Cust"},
        "branchName": "Jakarta",
        "detailItem": [_raw_line()],
    }
    out = normalize_delivery_note(raw)
    assert out["number"] == "DO/2026/11/12/000027"
    assert out["line_identity_complete"] is True
    assert out["loading_eligible"] is True
    assert out["so_line_cross_verified"] is False
    assert out["line_items"][0]["qty"] == 4000.0
    assert out["line_items"][0]["accurate_sj_line_id"] == "27001"


def test_unverified_quantity_does_not_complete_identity():
    line = normalize_delivery_note_line(_raw_line(quantity=""))
    assert line["qty_verified"] is False
    assert line["quantity"] is None
    assert line["qty"] == 0  # legacy numeric default
    assert line["line_identity_complete"] is False
    assert line["loading_eligible"] is False


def test_missing_unit_ratio_blocks_loading_eligibility():
    row = _raw_line()
    row.pop("unitRatio", None)
    line = normalize_delivery_note_line(row)
    assert line["line_identity_complete"] is True
    assert line["unit_ratio_verified"] is False
    assert line["loading_eligible"] is False


def test_non_pcs_uom_blocks_loading_eligibility():
    line = normalize_delivery_note_line(_raw_line(itemUnit={"name": "BOX"}))
    assert line["uom"] == "BOX"
    assert line["uom_packing_compatible"] is False
    assert line["line_identity_complete"] is True
    assert line["loading_eligible"] is False


def test_blank_uom_blocks_loading_eligibility():
    line = normalize_delivery_note_line(_raw_line(itemUnit=None, unit=None, uom=None))
    assert line["uom"] == ""
    assert line["uom_packing_compatible"] is False
    assert line["loading_eligible"] is False
