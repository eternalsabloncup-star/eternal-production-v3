"""Offline receipt contract regression; never contacts Accurate."""

import pytest

from app.normalize import normalize_receipt


@pytest.mark.parametrize("value", [0, -1, "0.00", "123.45"])
def test_explicit_total_preserved_without_positive_fallback(value):
    row = normalize_receipt({"id": 900, "status": "POSTED", "totalAmount": value,
                             "paymentAmount": 999, "salesOrder": {"id": 700, "number": "SO-1"}})
    assert row["amount"] == float(value)
    assert isinstance(row["amount"], (int, float))
    assert row["amount_decimal"] == str(value)
    assert row["id"] == "900"
    assert row["sales_order_id"] == "700"
    assert row["sales_order_number"] == "SO-1"


def test_receipt_number_is_not_a_canonical_id():
    assert normalize_receipt({"number": "RCP-900"})["id"] == ""


def test_ambiguous_so_not_fabricated_as_canonical_id():
    row = normalize_receipt({"id": 900, "salesOrder": [{"id": 700}, {"id": 701}]})
    assert row["sales_order_id"] is None


def test_decimal_precision_preserved_without_changing_numeric_contract():
    row = normalize_receipt({"id": 900, "totalAmount": "99999999999999.99"})
    assert isinstance(row["amount"], float)
    assert row["amount_decimal"] == "99999999999999.99"
