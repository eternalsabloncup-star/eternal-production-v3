"""Focused tests for Accurate API Token 1.0.3 auth (fake credentials only)."""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.accurate_auth import api_signature, api_timestamp, auth_headers, normalize_host
from app.accurate_client import AccurateClient, AccurateUpstreamError
from app.config import GatewaySettings

FAKE_TOKEN = "test-api-token-not-real"
FAKE_SECRET = "test-signature-secret-not-real"


def test_timestamp_format_wib():
    dt = datetime(2026, 3, 20, 10, 5, 9, tzinfo=ZoneInfo("Asia/Jakarta"))
    assert api_timestamp(dt) == "20/03/2026 10:05:09"


def test_signature_hmac_sha256_base64():
    ts = "20/03/2026 10:05:09"
    expected = base64.b64encode(
        hmac.new(FAKE_SECRET.encode(), ts.encode(), hashlib.sha256).digest()
    ).decode()
    assert api_signature(FAKE_SECRET, ts) == expected


def test_auth_headers_contain_bearer_timestamp_signature():
    headers = auth_headers(
        api_token=FAKE_TOKEN,
        signature_secret=FAKE_SECRET,
        now=datetime(2026, 3, 20, 10, 5, 9, tzinfo=ZoneInfo("Asia/Jakarta")),
    )
    assert headers["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert headers["X-Api-Timestamp"] == "20/03/2026 10:05:09"
    assert headers["X-Api-Signature"] == api_signature(
        FAKE_SECRET, "20/03/2026 10:05:09"
    )
    assert FAKE_SECRET not in headers["X-Api-Signature"]
    assert FAKE_SECRET not in headers["Authorization"]


def test_normalize_host():
    assert normalize_host("https://public.accurate.id/accurate/") == (
        "https://public.accurate.id"
    )
    assert normalize_host("zeus.accurate.id") == "https://zeus.accurate.id"


def _settings(**kwargs) -> GatewaySettings:
    base = {
        "ACCURATE_API_TOKEN": FAKE_TOKEN,
        "ACCURATE_SIGNATURE_SECRET": FAKE_SECRET,
        "ACCURATE_ACCOUNT_BASE": "https://account.accurate.id",
        "GATEWAY_MODE": "live",
        "GATEWAY_M2M_TOKEN": "test-m2m",
    }
    base.update(kwargs)
    return GatewaySettings(_env_file=None, **base)


def _patch_client(handler: Callable[[httpx.Request], httpx.Response], monkeypatch):
    """Route AccurateClient httpx calls through an in-memory mock transport."""
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs = dict(kwargs)
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs["follow_redirects"] = False
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_api_token_do_resolves_host_and_lists_so(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        host = request.url.host
        if host == "account.accurate.id" and path.endswith("/api/api-token.do"):
            assert request.method == "POST"
            assert request.headers["Authorization"] == f"Bearer {FAKE_TOKEN}"
            assert "X-Api-Timestamp" in request.headers
            assert "X-Api-Signature" in request.headers
            return httpx.Response(
                200,
                json={
                    "s": True,
                    "d": {
                        "database": {
                            "id": 99,
                            "host": "https://public.accurate.id",
                        }
                    },
                },
            )
        if host == "public.accurate.id" and "sales-order/list.do" in path:
            return httpx.Response(
                200,
                json={
                    "s": True,
                    "d": [
                        {
                            "number": "SO/TEST/1",
                            "statusName": "OPEN",
                            "customer": {"id": 1, "name": "X"},
                            "branch": {"id": 2, "name": "JKT"},
                            "totalAmount": 1000,
                        }
                    ],
                },
            )
        return httpx.Response(404, json={"s": False, "d": "unexpected"})

    _patch_client(handler, monkeypatch)
    client = AccurateClient(_settings())
    rows = await client.list_sales_orders(limit=10)
    assert len(rows) == 1
    assert rows[0]["number"] == "SO/TEST/1"
    assert any(r.url.path.endswith("/api/api-token.do") for r in seen)


@pytest.mark.asyncio
async def test_http_308_resigns_and_updates_host(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        path = request.url.path
        assert "X-Api-Signature" in request.headers
        if host == "account.accurate.id":
            return httpx.Response(
                200,
                json={
                    "s": True,
                    "d": {"database": {"id": 1, "host": "https://old.accurate.id"}},
                },
            )
        if host == "old.accurate.id" and "sales-order/detail.do" in path:
            return httpx.Response(
                308,
                headers={
                    "Location": (
                        "https://new.accurate.id/accurate/api/sales-order/detail.do"
                    )
                },
            )
        if host == "new.accurate.id" and "sales-order/detail.do" in path:
            return httpx.Response(
                200,
                json={
                    "s": True,
                    "d": {
                        "number": "SO/X",
                        "statusName": "OPEN",
                        "detailItem": [],
                        "customer": {"id": 1, "name": "A"},
                        "branch": {"id": 1, "name": "B"},
                    },
                },
            )
        return httpx.Response(500, json={"s": False})

    _patch_client(handler, monkeypatch)
    client = AccurateClient(_settings())
    detail = await client.get_sales_order("SO/X")
    assert detail["number"] == "SO/X"
    assert client._host == "https://new.accurate.id"


@pytest.mark.asyncio
async def test_receipt_and_delivery_readonly_paths(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        path = request.url.path
        if host == "account.accurate.id":
            return httpx.Response(
                200,
                json={
                    "s": True,
                    "d": {
                        "database": {"id": 1, "host": "https://public.accurate.id"}
                    },
                },
            )
        if "sales-receipt/detail.do" in path:
            return httpx.Response(
                200,
                json={
                    "s": True,
                    "d": {
                        "id": 10,
                        "number": "RCP-1",
                        "statusName": "POSTED",
                        "totalAmount": 100,
                        "customer": {"id": 1, "name": "A"},
                    },
                },
            )
        if "delivery-order/detail.do" in path:
            return httpx.Response(
                200,
                json={
                    "s": True,
                    "d": {
                        "id": 20,
                        "number": "SJ-1",
                        "statusName": "DELIVERED",
                        "detailItem": [{"itemNo": "SKU", "quantity": 2}],
                        "customer": {"id": 1, "name": "A"},
                    },
                },
            )
        return httpx.Response(404, json={"s": False})

    _patch_client(handler, monkeypatch)
    client = AccurateClient(_settings())
    receipt = await client.get_receipt("10")
    sj = await client.get_delivery_note("20")
    assert receipt["number"] == "RCP-1"
    assert sj["number"] == "SJ-1"
    assert sj["line_items"][0]["qty"] == 2.0


@pytest.mark.asyncio
async def test_missing_signature_secret_fails_closed():
    client = AccurateClient(_settings(**{"ACCURATE_SIGNATURE_SECRET": ""}))
    assert client.configured() is False
    with pytest.raises(AccurateUpstreamError) as exc:
        await client.list_sales_orders()
    assert exc.value.code == "accurate_credentials_missing"
    assert exc.value.status_code == 503
