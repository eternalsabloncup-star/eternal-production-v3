"""GATEWAY_MODE=live must never serve fixtures/demo SO/receipts/SJ."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["GATEWAY_MODE"] = "fixture"
os.environ["GATEWAY_M2M_TOKEN"] = "test-m2m-token"
os.environ.pop("ACCURATE_API_TOKEN", None)
os.environ.pop("ACCURATE_SIGNATURE_SECRET", None)

from app import fixtures  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

get_settings.cache_clear()


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-m2m-token"}


@pytest.fixture
async def client():
    get_settings.cache_clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_live_missing_creds_never_calls_fixtures(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("GATEWAY_MODE", "live")
    monkeypatch.setenv("GATEWAY_M2M_TOKEN", "test-m2m-token")
    monkeypatch.delenv("ACCURATE_API_TOKEN", raising=False)
    monkeypatch.delenv("ACCURATE_SIGNATURE_SECRET", raising=False)
    get_settings.cache_clear()

    def boom(*_a, **_k):
        raise AssertionError("fixture corpus must not be used when GATEWAY_MODE=live")

    monkeypatch.setattr(fixtures, "list_sales_orders", boom)
    monkeypatch.setattr(fixtures, "get_sales_order", boom)
    monkeypatch.setattr(fixtures, "get_receipt", boom)
    monkeypatch.setattr(fixtures, "get_delivery_note", boom)

    listed = await client.get("/sales-orders", headers=_auth())
    assert listed.status_code == 503
    assert listed.json()["detail"]["code"] == "accurate_credentials_missing"
    assert listed.json()["detail"]["message"].find("fixture") >= 0

    # Fixture demo ids must not succeed
    for path in (
        "/sales-orders/SO-LIVE-001",
        "/receipts/RCP-OK-1",
        "/delivery-notes/SJ-OK-1",
    ):
        r = await client.get(path, headers=_auth())
        assert r.status_code == 503, path
        assert r.json()["detail"]["code"] == "accurate_credentials_missing"

    monkeypatch.setenv("GATEWAY_MODE", "fixture")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_live_upstream_error_does_not_fallback_to_fixture(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("GATEWAY_MODE", "live")
    monkeypatch.setenv("GATEWAY_M2M_TOKEN", "test-m2m-token")
    monkeypatch.setenv("ACCURATE_API_TOKEN", "fake-token-not-real")
    monkeypatch.setenv("ACCURATE_SIGNATURE_SECRET", "fake-secret-not-real")
    get_settings.cache_clear()

    def boom(*_a, **_k):
        raise AssertionError("fixture fallback forbidden after live upstream failure")

    monkeypatch.setattr(fixtures, "get_sales_order", boom)

    from app.accurate_client import AccurateClient, AccurateUpstreamError

    async def fail_get(self, number: str):
        raise AccurateUpstreamError(
            "accurate_unreachable", "upstream unreachable", status_code=502
        )

    monkeypatch.setattr(AccurateClient, "get_sales_order", fail_get)

    r = await client.get("/sales-orders/SO-LIVE-001", headers=_auth())
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "accurate_unreachable"
    body = r.json()
    assert body.get("source") != "fixture"
    assert "sales_order" not in body

    monkeypatch.setenv("GATEWAY_MODE", "fixture")
    monkeypatch.delenv("ACCURATE_API_TOKEN", raising=False)
    monkeypatch.delenv("ACCURATE_SIGNATURE_SECRET", raising=False)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_invalid_gateway_mode_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("GATEWAY_MODE", "staging-ish")
    monkeypatch.setenv("GATEWAY_M2M_TOKEN", "test-m2m-token")
    get_settings.cache_clear()
    r = await client.get("/sales-orders", headers=_auth())
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "gateway_mode_invalid"
    monkeypatch.setenv("GATEWAY_MODE", "fixture")
    get_settings.cache_clear()
