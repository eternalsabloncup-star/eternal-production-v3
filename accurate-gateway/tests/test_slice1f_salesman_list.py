"""Slice 1F: salesmanList mapping; sales never falls back to creator/branch."""

from __future__ import annotations

from app.contracts import so_detail, so_list_row
from app.normalize import _extract_sales, normalize_sales_order, normalize_sales_order_list_item


def test_salesman_list_preferred_over_scalar_and_creator():
    raw = {
        "id": 11,
        "number": "PO/SALES/1",
        "statusName": "OPEN",
        "customer": {"id": 1, "name": "Cust"},
        "branch": {"id": 50, "name": "Yogyakarta"},
        "branchName": "Yogyakarta",
        "createdUserName": "Admin Creator",
        "salesPersonName": "Legacy Scalar Should Lose",
        "salesmanList": [
            {"name": "Sales Jogja Official"},
            {"salesmanName": "Sales B"},
        ],
        "detailItem": [],
    }
    name, source = _extract_sales(raw)
    assert name == "Sales Jogja Official, Sales B"
    assert source == "salesmanList"
    mapped = so_detail(normalize_sales_order(raw))
    assert mapped["sales"] == "Sales Jogja Official, Sales B"
    assert mapped["sales_source"] == "salesmanList"
    assert mapped["created_by_user"] == "Admin Creator"
    assert mapped["sales"] != mapped["created_by_user"]


def test_missing_sales_stays_null_not_creator_or_branch():
    raw = {
        "id": 12,
        "number": "PO/SALES/2",
        "statusName": "OPEN",
        "customer": {"id": 1, "name": "Cust"},
        "branch": {"id": 50, "name": "Yogyakarta"},
        "branchName": "Yogyakarta",
        "createdUserName": "Admin Creator",
        "detailItem": [],
    }
    name, source = _extract_sales(raw)
    assert name is None
    assert source is None
    mapped = so_detail(normalize_sales_order(raw))
    assert mapped["sales"] is None
    assert mapped["sales_source"] is None
    assert mapped["created_by_user"] == "Admin Creator"
    assert mapped["branch_name"] == "Yogyakarta"
    # Contract must not substitute creator into sales.
    assert mapped["sales"] != mapped["created_by_user"]


def test_list_row_exposes_sales_source_from_salesman_list():
    row = normalize_sales_order_list_item(
        {
            "id": 13,
            "number": "PO/SALES/3",
            "statusName": "OPEN",
            "customer": {"id": 1, "name": "Cust"},
            "branch": {"id": 50, "name": "Yogyakarta"},
            "createdUserName": "Admin Creator",
            "salesmanList": [{"name": "Sales List Only"}],
            "totalAmount": 1,
        }
    )
    assert row["sales"] == "Sales List Only"
    assert row["sales_source"] == "salesmanList"
    contract = so_list_row(row)
    assert contract["sales"] == "Sales List Only"
    assert contract["sales_source"] == "salesmanList"
