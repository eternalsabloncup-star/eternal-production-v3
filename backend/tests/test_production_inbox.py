"""Accurate inbox + gateway contract tests."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.accurate_read_gateway import (
    ReadGateway,
    get_sales_order,
    list_sales_orders,
)


class Gateway:
    async def get(self, path, *, params=None):
        if path == "/sales-orders":
            return {
                "total": 1,
                "rows": [
                    {
                        "number": "SO/TEST/001",
                        "customer": "Customer",
                        "branch_id": "branch-a",
                        "import_status": "imported",
                    }
                ],
            }
        return {
            "preview": {
                "accurate_id": "501",
                "number": "SO/TEST/001",
                "po_number": None,
                "customer": "Customer",
                "branch_id": "branch-a",
                "buffer_stock": None,
                "urgent_state": None,
                "line_items": [
                    {
                        "accurate_line_id": "9001",
                        "accurate_item_id": "77",
                        "item_code": "123",
                        "name": "Item",
                        "quantity": 2500,
                        "unit": "pcs",
                        "production_process": "unknown",
                    }
                ],
                "total_quantity": 2500,
            }
        }


@pytest.mark.asyncio
async def test_inbox_no_fabricated_approval_or_qty():
    data = await list_sales_orders(Gateway(), page=1, limit=50, keyword="")
    row = data["rows"][0]
    assert row["production_status"] == "Baru"
    assert row["total_quantity"] is None
    assert row["line_items"] is None
    assert data["mode"] == "live"


@pytest.mark.asyncio
async def test_detail_has_exact_lines():
    so = await get_sales_order(Gateway(), "SO/TEST/001")
    assert so["total_quantity"] == 2500
    assert so["line_items"][0]["item_code"] == "123"
    assert so["line_items"][0]["accurate_line_id"] == "9001"
    assert so["line_items"][0]["production_process"] == "unknown"
    assert so["buffer_stock"] is None
    assert so["urgent_state"] is None


@pytest.mark.asyncio
async def test_inbox_list_keeps_unknown_classifications_null():
    data = await list_sales_orders(Gateway(), page=1, limit=50, keyword="")
    row = data["rows"][0]
    assert row["buffer_stock"] is None
    assert row["urgent_state"] is None


@pytest.mark.asyncio
async def test_unconfigured_gateway_fails_closed():
    gw = ReadGateway(base_url="", token="")
    with pytest.raises(HTTPException) as exc:
        await gw.get("/sales-orders")
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "gateway_unconfigured"


@pytest.mark.asyncio
async def test_insecure_gateway_rejected():
    gw = ReadGateway(base_url="http://example.com", token="secret")
    with pytest.raises(HTTPException) as exc:
        await gw.get("/sales-orders")
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "gateway_insecure_url"
