"""Health and readiness endpoint tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "ETERNAL PRODUCTION V3"
    assert "version" in payload


@pytest.mark.asyncio
async def test_ready_requires_postgres(client: AsyncClient) -> None:
    response = await client.get("/api/v1/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["database"] == "ok"


@pytest.mark.asyncio
async def test_unknown_route_structured_error(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "http_error"
