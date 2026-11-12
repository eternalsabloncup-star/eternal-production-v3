"""Slice 1M: backend qty verification passthrough + eligibility reject."""

from __future__ import annotations

import math

import pytest
from fastapi import HTTPException

from app.services.accurate_read_gateway import get_sales_order


class _Gateway:
    def __init__(self, payload: dict):
        self.payload = payload

    async def get(self, path, *, params=None):
        assert "/sales-orders/" in path
        return {"sales_order": self.payload}


@pytest.mark.asyncio
async def test_backend_preserves_verified_2000_mixed_print():
    so = await get_sales_order(
        _Gateway(
            {
                "accurate_id": "1",
                "number": "SO/SYN/OK",
                "customer": "Cust",
                "branch_id": "50",
                "branch_name": "Yogyakarta",
                "sales": None,
                "sales_source": None,
                "created_by_user": "Admin",
                "total_quantity": 2000,
                "total_quantity_verified": True,
                "line_count": 2,
                "line_items": [
                    {
                        "accurate_line_id": "1",
                        "item_code": "A",
                        "name": "Print",
                        "quantity": 1000,
                        "qty_verified": True,
                        "unit": "PCS",
                        "production_process": "print",
                    },
                    {
                        "accurate_line_id": "2",
                        "item_code": "B",
                        "name": "NonPrint",
                        "quantity": 1000,
                        "qty_verified": True,
                        "unit": "PCS",
                        "production_process": "non_print",
                    },
                ],
            }
        ),
        "SO/SYN/OK",
    )
    assert so["total_quantity"] == 2000
    assert so["total_quantity_verified"] is True
    assert so["line_items"][0]["qty_verified"] is True
    assert so["line_items"][1]["production_process"] == "non_print"
    assert so["sales"] is None
    assert so["created_by_user"] == "Admin"


@pytest.mark.asyncio
async def test_backend_missing_qty_not_verified_zero():
    so = await get_sales_order(
        _Gateway(
            {
                "accurate_id": "2",
                "number": "SO/SYN/MISS",
                "customer": "Cust",
                "branch_id": "50",
                "branch_name": "Yogyakarta",
                "line_items": [
                    {
                        "accurate_line_id": "1",
                        "quantity": 1000,
                        "qty_verified": True,
                        "production_process": "print",
                    },
                    {
                        "accurate_line_id": "2",
                        "quantity": None,
                        "qty_verified": False,
                        "production_process": "non_print",
                    },
                ],
            }
        ),
        "SO/SYN/MISS",
    )
    assert so["line_items"][1]["quantity"] is None
    assert so["line_items"][1]["qty_verified"] is False
    assert so["total_quantity"] is None
    assert so["total_quantity_verified"] is False


@pytest.mark.asyncio
async def test_backend_nan_infinity_rejected():
    so = await get_sales_order(
        _Gateway(
            {
                "accurate_id": "3",
                "number": "SO/SYN/NAN",
                "customer": "Cust",
                "branch_id": "50",
                "branch_name": "Yogyakarta",
                "line_items": [
                    {
                        "accurate_line_id": "1",
                        "quantity": float("nan"),
                        "qty_verified": True,
                        "production_process": "print",
                    }
                ],
            }
        ),
        "SO/SYN/NAN",
    )
    assert so["line_items"][0]["quantity"] is None
    assert so["line_items"][0]["qty_verified"] is False
    assert so["total_quantity_verified"] is False


@pytest.mark.asyncio
async def test_sync_rejects_unverified_qty():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.services.production.prep import sync_job_lines_from_so_detail

    session = AsyncMock()
    job = SimpleNamespace(id=1)
    with pytest.raises(HTTPException) as exc:
        await sync_job_lines_from_so_detail(
            session,
            job,
            [
                {
                    "accurate_line_id": "L1",
                    "quantity": None,
                    "qty_verified": False,
                    "production_process": "print",
                }
            ],
        )
    assert exc.value.status_code == 422
    assert "terverifikasi" in str(exc.value.detail).lower()


def test_finite_helper():
    assert math.isfinite(0.0)
    assert not math.isfinite(float("nan"))
    assert not math.isfinite(float("inf"))
