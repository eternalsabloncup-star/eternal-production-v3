"""Reproduce live SO detail 404: Accurate detail.do requires id, not number."""

from __future__ import annotations

import os

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.accurate_client import AccurateClient, AccurateUpstreamError
from app.config import get_settings

from tests.test_api_token_auth import _patch_client, _settings


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-m2m"}


@pytest.mark.asyncio
async def test_detail_by_document_number_resolves_id_when_number_param_404(
    monkeypatch,
):
    """Observed failure: detail.do?number=… → 404; list has id; detail.do?id= → 200."""
    seen_detail_params: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        path = request.url.path
        if host == "account.accurate.id":
            return httpx.Response(
                200,
                json={
                    "s": True,
                    "d": {
                        "database": {
                            "id": 823960,
                            "host": "https://public.accurate.id",
                        }
                    },
                },
            )
        if "sales-order/detail.do" in path:
            params = {k: v for k, v in request.url.params.multi_items()}
            seen_detail_params.append(params)
            if "number" in params and "id" not in params:
                return httpx.Response(404, json={"s": False, "d": None})
            if params.get("id") == "90042":
                return httpx.Response(
                    200,
                    json={
                        "s": True,
                        "d": {
                            "id": 90042,
                            "number": "SO/EP/100",
                            "statusName": "OPEN",
                            "detailItem": [
                                {
                                    "itemNo": "SKU-1",
                                    "quantity": 3,
                                    "itemUnit": "PCS",
                                }
                            ],
                            "customer": {"id": 1, "name": "A"},
                            "branch": {"id": 1, "name": "B"},
                        },
                    },
                )
            return httpx.Response(404, json={"s": False})
        if "sales-order/list.do" in path:
            return httpx.Response(
                200,
                json={
                    "s": True,
                    "d": [{"id": 90042, "number": "SO/EP/100"}],
                    "sp": {"rowCount": 1},
                },
            )
        return httpx.Response(500, json={"s": False})

    _patch_client(handler, monkeypatch)
    client = AccurateClient(_settings(**{"ACCURATE_DATABASE_ID": "823960"}))
    detail = await client.get_sales_order("SO/EP/100")
    assert detail["number"] == "SO/EP/100"
    assert detail["accurate_id"] == "90042"
    assert detail["line_items"][0]["qty"] == 3.0
    assert any(p.get("id") == "90042" for p in seen_detail_params)


@pytest.mark.asyncio
async def test_detail_by_internal_id_uses_id_query_only(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
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
        if "sales-order/detail.do" in path:
            assert request.url.params.get("id") == "55"
            assert request.url.params.get("number") is None
            return httpx.Response(
                200,
                json={
                    "s": True,
                    "d": {
                        "id": 55,
                        "number": "SO-N",
                        "statusName": "OPEN",
                        "detailItem": [],
                        "customer": {"id": 1, "name": "A"},
                        "branch": {"id": 1, "name": "B"},
                    },
                },
            )
        if "sales-order/list.do" in path:
            pytest.fail("list resolve must not run for numeric id keys")
        return httpx.Response(500, json={"s": False})

    _patch_client(handler, monkeypatch)
    client = AccurateClient(_settings())
    detail = await client.get_sales_order("55")
    assert detail["accurate_id"] == "55"


@pytest.mark.asyncio
async def test_upstream_404_code_sanitized(monkeypatch):
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
        if "sales-order/list.do" in request.url.path:
            return httpx.Response(
                200, json={"s": True, "d": [], "sp": {"rowCount": 0}}
            )
        return httpx.Response(404, json={"s": False})

    _patch_client(handler, monkeypatch)
    client = AccurateClient(_settings())
    with pytest.raises(AccurateUpstreamError) as exc:
        await client.get_sales_order("SO-MISSING")
    assert exc.value.code == "accurate_not_found"
    assert exc.value.status_code == 404
    assert "SO-MISSING" not in (exc.value.message or "")


@pytest.mark.asyncio
async def test_gateway_route_path_with_slashes_live(monkeypatch):
    monkeypatch.setenv("GATEWAY_MODE", "live")
    monkeypatch.setenv("GATEWAY_M2M_TOKEN", "test-m2m")
    monkeypatch.setenv("ACCURATE_API_TOKEN", "tok")
    monkeypatch.setenv("ACCURATE_SIGNATURE_SECRET", "sec")
    get_settings.cache_clear()

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
        if "sales-order/list.do" in request.url.path:
            return httpx.Response(
                200,
                json={"s": True, "d": [{"id": 12, "number": "SO/A/1"}]},
            )
        if "sales-order/detail.do" in request.url.path:
            if request.url.params.get("id") == "12":
                return httpx.Response(
                    200,
                    json={
                        "s": True,
                        "d": {
                            "id": 12,
                            "number": "SO/A/1",
                            "statusName": "OPEN",
                            "detailItem": [],
                            "customer": {"id": 1, "name": "A"},
                            "branch": {"id": 1, "name": "B"},
                        },
                    },
                )
            return httpx.Response(404, json={"s": False})
        return httpx.Response(500, json={"s": False})

    _patch_client(handler, monkeypatch)
    # Import app after env so Depends(get_settings) sees live mode.
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/sales-orders/SO/A/1", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "accurate_live"
    assert body["live_verified"] is True
    assert body["sales_order"]["accurate_id"] == "12"
    get_settings.cache_clear()
    # Avoid leaking live mode into later fixture tests in the same process.
    os.environ["GATEWAY_MODE"] = "fixture"
    get_settings.cache_clear()
