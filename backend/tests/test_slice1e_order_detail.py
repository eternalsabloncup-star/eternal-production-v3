"""Slice 1E: backend passes through Accurate detail parity fields."""

from __future__ import annotations

import pytest

from app.services.accurate_read_gateway import get_sales_order, normalize_summary


class Gateway:
    async def get(self, path, *, params=None):
        assert "/sales-orders/" in path
        return {
            "sales_order": {
                "accurate_id": "990055",
                "number": "PO/11/11/2026/000005",
                "customer": "AD MELIORA COFFEE & EATERY",
                "branch_id": "50",
                "branch_name": "Yogyakarta",
                "sales": "Sales Jogja Official",
                "created_by_user": "Admin Creator",
                "order_date": "2026-11-11",
                "address": "Jl. Contoh No. 1",
                "payment_terms": "NET 30",
                "expedition": "Internal",
                "delivery_zone": "Jogja Kota",
                "estimated_delivery": "2026-11-20",
                "notes": "Catatan PO uji",
                "buffer_stock": None,
                "urgent_state": None,
                "total_quantity": 2000,
                "line_count": 2,
                "line_items": [
                    {
                        "accurate_line_id": "7001",
                        "accurate_item_id": "100003",
                        "item_code": "100003",
                        "name": "12 oz PET Datar 11 gr SJP",
                        "quantity": 1000,
                        "unit": "PCS",
                        "production_process": "print",
                        "color": "Hijau Army",
                        "notes": "Cetak logo",
                    },
                    {
                        "accurate_line_id": "7002",
                        "accurate_item_id": "100460",
                        "item_code": "100460",
                        "name": "LID PET Strawless Tam",
                        "quantity": 1000,
                        "unit": "PCS",
                        "production_process": "non_print",
                        "color": "Bening",
                    },
                ],
            }
        }


@pytest.mark.asyncio
async def test_backend_detail_preserves_mixed_print_and_header():
    so = await get_sales_order(Gateway(), "PO/11/11/2026/000005")
    assert so["customer"] == "AD MELIORA COFFEE & EATERY"
    assert so["total_quantity"] == 2000
    assert so["line_count"] == 2
    assert so["sales"] == "Sales Jogja Official"
    assert so["created_by_user"] == "Admin Creator"
    assert so["sales"] != so["created_by_user"]
    assert so["branch_name"] == "Yogyakarta"
    assert so["line_items"][0]["production_process"] == "print"
    assert so["line_items"][1]["production_process"] == "non_print"
    assert so["buffer_stock"] is None


def test_list_summary_keeps_lines_null():
    row = normalize_summary(
        {
            "accurate_id": "1",
            "number": "SO/1",
            "customer": "A",
            "branch_id": "50",
            "branch_name": "Yogyakarta",
            "sales": "Sales A",
        }
    )
    assert row["line_items"] is None
    assert row["total_quantity"] is None
    assert row["branch_name"] == "Yogyakarta"
    assert row["sales"] == "Sales A"
