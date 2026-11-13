"""Sales order identity + live list pagination contract."""

from __future__ import annotations

import httpx
import pytest

from app.accurate_client import AccurateClient
from app.contracts import so_detail, so_list_row
from app.normalize import normalize_sales_order, normalize_sales_order_list_item

from tests.test_api_token_auth import FAKE_SECRET, FAKE_TOKEN, _patch_client, _settings


def test_so_list_preserves_accurate_id_and_separates_po():
    row = normalize_sales_order_list_item(
        {
            "id": 823001,
            "number": "SO/EP/100",
            "poNumber": "PO-FROM-CUST",
            "statusName": "OPEN",
            "customer": {"id": 1, "name": "A"},
            "branch": {"id": 2, "name": "JKT"},
            "totalAmount": 10,
        }
    )
    out = so_list_row(row)
    assert out["accurate_id"] == "823001"
    assert out["number"] == "SO/EP/100"
    assert out["po_number"] == "PO-FROM-CUST"


def test_so_list_does_not_fabricate_po_from_so_number():
    row = normalize_sales_order_list_item(
        {
            "id": 9,
            "number": "SO-ONLY",
            "statusName": "OPEN",
            "customer": {"id": 1, "name": "A"},
            "branch": {"id": 2, "name": "JKT"},
            "totalAmount": 1,
        }
    )
    out = so_list_row(row)
    assert out["number"] == "SO-ONLY"
    assert out["po_number"] is None


def test_so_detail_links_are_not_evidence_authority():
    detail = normalize_sales_order(
        {
            "id": 1,
            "number": "SO-1",
            "statusName": "OPEN",
            "customer": {"id": 1, "name": "A"},
            "branch": {"id": 1, "name": "B"},
            "detailItem": [],
        }
    )
    mapped = so_detail(detail)
    assert mapped["links"]["receipt_ids"] == []
    assert mapped["links"]["evidence_authority"] is False
    assert mapped["links"]["receipts_present"] is False


@pytest.mark.asyncio
async def test_live_list_uses_accurate_total_and_page(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "account.accurate.id":
            return httpx.Response(
                200,
                json={
                    "s": True,
                    "d": {
                        "database": {"id": 1, "host": "https://public.accurate.id"}
                    },
                },
            )
        assert request.url.params.get("sp.page") == "2"
        assert request.url.params.get("sp.pageSize") == "5"
        return httpx.Response(
            200,
            json={
                "s": True,
                "d": [
                    {
                        "id": i,
                        "number": f"SO-{i}",
                        "statusName": "OPEN",
                        "customer": {"id": 1, "name": "A"},
                        "branch": {"id": 1, "name": "B"},
                        "totalAmount": 1,
                    }
                    for i in range(5)
                ],
                "sp": {"page": 2, "pageSize": 5, "rowCount": 50},
            },
        )

    _patch_client(handler, monkeypatch)
    client = AccurateClient(
        _settings(
            **{
                "ACCURATE_API_TOKEN": FAKE_TOKEN,
                "ACCURATE_SIGNATURE_SECRET": FAKE_SECRET,
            }
        )
    )
    listed = await client.list_sales_orders(limit=5, page=2)
    assert listed["accurate_total"] == 50
    assert len(listed["rows"]) == 5
    assert listed["page"] == 2
    assert listed["filter_incomplete"] is False


@pytest.mark.asyncio
async def test_branch_name_filter_marks_incomplete(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "account.accurate.id":
            return httpx.Response(
                200,
                json={
                    "s": True,
                    "d": {
                        "database": {"id": 1, "host": "https://public.accurate.id"}
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "s": True,
                "d": [
                    {
                        "id": 1,
                        "number": "SO-1",
                        "statusName": "OPEN",
                        "customer": {"id": 1, "name": "A"},
                        "branch": {"id": 1, "name": "Jakarta"},
                        "totalAmount": 1,
                    },
                    {
                        "id": 2,
                        "number": "SO-2",
                        "statusName": "OPEN",
                        "customer": {"id": 1, "name": "A"},
                        "branch": {"id": 2, "name": "Surabaya"},
                        "totalAmount": 1,
                    },
                ],
                "sp": {"rowCount": 200},
            },
        )

    _patch_client(handler, monkeypatch)
    client = AccurateClient(_settings())
    listed = await client.list_sales_orders(branch="Jakarta", limit=50, page=1)
    assert len(listed["rows"]) == 1
    assert listed["filter_incomplete"] is True
    assert listed["accurate_total"] == 200
