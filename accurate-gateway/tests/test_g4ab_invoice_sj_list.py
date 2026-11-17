"""G4A/G4B — sales-invoice outstanding + delivery-order list (fixture / fail-closed)."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["GATEWAY_MODE"] = "fixture"
os.environ["GATEWAY_M2M_TOKEN"] = "test-m2m-token"
os.environ.pop("ACCURATE_API_TOKEN", None)
os.environ.pop("ACCURATE_DATABASE_ID", None)

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.normalize import normalize_sales_invoice  # noqa: E402
from app.reconcile import reconcile_id_pages  # noqa: E402

get_settings.cache_clear()


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-m2m-token"}


@pytest.mark.asyncio
async def test_g4a_sales_invoice_list_and_detail_owing_contract():
    get_settings.cache_clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/sales-invoices", headers=_auth())
        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert body["live_verified"] is False
        assert body["source"] == "fixture"
        assert body["reconciliation"]["full_universe_verified"] is False
        assert body["reconciliation"]["duplicate_ids"] == 0
        detail = await client.get("/sales-invoices/INV-PARTIAL-1", headers=_auth())
        assert detail.status_code == 200
        inv = detail.json()
        assert inv["outstanding_amount"] == "400.00"
        assert inv["invoice_total"] == "1000.00"
        assert inv["paid_amount"] == "600.00"
        assert inv["financial_payment_status"] == "Sebagian"
        assert inv["verified"] is False  # fixture never settles Live finance
        unknown = await client.get("/sales-invoices/INV-UNKNOWN-1", headers=_auth())
        assert unknown.json()["owing_field_present"] is False
        assert unknown.json()["financial_payment_status"] is None


def test_g4a_normalize_never_uses_total_as_owing():
    row = normalize_sales_invoice(
        {
            "id": 9,
            "number": "INV-X",
            "totalAmount": 1000,
            # no primeOwing
        }
    )
    assert row["invoice_total"] == "1000.00"
    assert row["outstanding_amount"] is None
    assert row["financial_payment_status"] is None
    assert row["owing_field_present"] is False
    row2 = normalize_sales_invoice(
        {"id": 10, "number": "INV-Y", "totalAmount": 1000, "primeOwing": 250}
    )
    assert row2["outstanding_amount"] == "250.00"
    assert row2["financial_payment_status"] == "Sebagian"
    assert row2["paid_amount"] == "750.00"


@pytest.mark.asyncio
async def test_g4b_delivery_notes_list_pagination_and_internal_id():
    get_settings.cache_clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page1 = await client.get(
            "/delivery-notes", headers=_auth(), params={"page": 1, "limit": 2}
        )
        assert page1.status_code == 200, page1.text
        b1 = page1.json()
        assert b1["live_verified"] is False
        assert b1["full_accurate_sj_universe"] is False
        assert b1["pageSize"] == 2
        assert len(b1["rows"]) <= 2
        assert b1["reconciliation"]["full_universe_verified"] is False
        # Internal id preferred for detail
        first = b1["rows"][0]
        assert first.get("accurate_id") or str(first.get("id", "")).isdigit()
        detail = await client.get(
            f"/delivery-notes/{first['accurate_id'] or first['id']}",
            headers=_auth(),
        )
        assert detail.status_code == 200
        # Number lookup still works
        by_number = await client.get("/delivery-notes/SJ-OK-1", headers=_auth())
        assert by_number.status_code == 200


def test_g4b_reconcile_detects_duplicates_and_refuses_universe_claim():
    pages = [
        [{"accurate_id": "1"}, {"accurate_id": "2"}],
        [{"accurate_id": "2"}, {"accurate_id": "3"}],
    ]
    recon = reconcile_id_pages(pages, claimed_total=3)
    assert recon["duplicate_ids"] == 1
    assert recon["unique_ids"] == 3
    assert recon["count_matches_claimed"] is False
    assert recon["full_universe_verified"] is False
