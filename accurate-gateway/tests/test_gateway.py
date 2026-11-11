"""Gateway integration, security, mismatch, reversal, concurrency tests."""

from __future__ import annotations

import asyncio
import os

import pytest
from httpx import ASGITransport, AsyncClient

# Fixture mode + M2M before app import resolves settings.
os.environ["GATEWAY_MODE"] = "fixture"
os.environ["GATEWAY_M2M_TOKEN"] = "test-m2m-token"
os.environ.pop("ACCURATE_API_TOKEN", None)
os.environ.pop("ACCURATE_DATABASE_ID", None)

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

get_settings.cache_clear()


@pytest.fixture
async def client():
    get_settings.cache_clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-m2m-token"}


@pytest.mark.asyncio
async def test_health_no_auth(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "fixture"
    assert body["live_verified"] is False
    assert body["read_only"] is True


@pytest.mark.asyncio
async def test_m2m_required(client: AsyncClient):
    r = await client.get("/sales-orders")
    assert r.status_code == 401
    r2 = await client.get("/sales-orders", headers={"Authorization": "Bearer wrong"})
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_list_and_detail_sales_orders(client: AsyncClient):
    listed = await client.get("/sales-orders?limit=20&page=1", headers=_auth())
    assert listed.status_code == 200
    payload = listed.json()
    assert "rows" in payload
    assert payload["live_verified"] is False
    assert payload["total"] >= 70
    assert len(payload["rows"]) == 20
    page2 = await client.get("/sales-orders?limit=20&page=2", headers=_auth())
    assert page2.status_code == 200
    assert page2.json()["rows"][0]["number"] != payload["rows"][0]["number"]

    detail = await client.get("/sales-orders/SO-LIVE-001", headers=_auth())
    assert detail.status_code == 200
    so = detail.json()["sales_order"]
    assert so["po_number"] == "SO-LIVE-001"
    assert so["line_items"][0]["item_code"] == "BOX-A"
    assert so["line_items"][0]["quantity"] == 100


@pytest.mark.asyncio
async def test_receipt_ok_cancelled_reversed_mismatch(client: AsyncClient):
    ok = await client.get("/receipts/RCP-OK-1", headers=_auth())
    assert ok.status_code == 200
    assert ok.json()["verifiable"] is True
    assert ok.json()["cancelled"] is False

    cancelled = await client.get("/receipts/RCP-CANCELLED", headers=_auth())
    assert cancelled.status_code == 200
    assert cancelled.json()["cancelled"] is True
    assert cancelled.json()["verifiable"] is False

    reversed_ = await client.get("/receipts/RCP-REVERSED", headers=_auth())
    assert reversed_.status_code == 200
    assert reversed_.json()["reversed"] is True
    assert reversed_.json()["verifiable"] is False

    mismatch = await client.get("/receipts/RCP-MISMATCH", headers=_auth())
    assert mismatch.status_code == 200
    assert mismatch.json()["sales_order_number"] == "SO-OTHER"
    assert mismatch.json()["customer"]["id"] == "C-999"


@pytest.mark.asyncio
async def test_delivery_note_ok_cancelled_mismatch(client: AsyncClient):
    ok = await client.get("/delivery-notes/SJ-OK-1", headers=_auth())
    assert ok.status_code == 200
    assert ok.json()["number"] == "SJ-OK-1"
    assert ok.json()["verifiable"] is True

    cancelled = await client.get("/delivery-notes/SJ-CANCELLED", headers=_auth())
    assert cancelled.json()["cancelled"] is True
    assert cancelled.json()["verifiable"] is False

    mismatch = await client.get("/delivery-notes/SJ-MISMATCH", headers=_auth())
    assert mismatch.json()["sales_order_number"] == "SO-OTHER"


@pytest.mark.asyncio
async def test_missing_documents_404(client: AsyncClient):
    for path in (
        "/sales-orders/SO-NOPE",
        "/receipts/RCP-NOPE",
        "/delivery-notes/SJ-NOPE",
    ):
        r = await client.get(path, headers=_auth())
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "document_not_found"


@pytest.mark.asyncio
async def test_live_mode_without_credentials_fails_closed(client: AsyncClient, monkeypatch):
    monkeypatch.setenv("GATEWAY_MODE", "live")
    monkeypatch.setenv("GATEWAY_M2M_TOKEN", "test-m2m-token")
    monkeypatch.delenv("ACCURATE_API_TOKEN", raising=False)
    monkeypatch.delenv("ACCURATE_SIGNATURE_SECRET", raising=False)
    monkeypatch.delenv("ACCURATE_DATABASE_ID", raising=False)
    get_settings.cache_clear()
    r = await client.get("/sales-orders/SO-LIVE-001", headers=_auth())
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "accurate_credentials_missing"
    monkeypatch.setenv("GATEWAY_MODE", "fixture")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_concurrent_reads(client: AsyncClient):
    async def one():
        return await client.get("/receipts/RCP-OK-1", headers=_auth())

    results = await asyncio.gather(*[one() for _ in range(20)])
    assert all(r.status_code == 200 for r in results)
    assert all(r.json()["id"] == "RCP-OK-1" for r in results)
