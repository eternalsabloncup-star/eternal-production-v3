"""G4 — integration coverage contract (Outstanding + SJ list fail-closed)."""

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

get_settings.cache_clear()


@pytest.mark.asyncio
async def test_integration_coverage_director_evidence_not_atomic_universe():
    get_settings.cache_clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.get("/integration-coverage")
        assert denied.status_code == 401
        ok = await client.get(
            "/integration-coverage",
            headers={"Authorization": "Bearer test-m2m-token"},
        )
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["read_only"] is True
        assert body["live_writes"] is False
        paths = {e["path"] for e in body["proven_endpoints"]}
        assert "/delivery-notes" in paths
        assert "/sales-invoices" in paths
        assert body["outstanding"]["status"] == "DIRECTOR_LIVE_EVIDENCE"
        assert body["outstanding"]["owing_field"] == "primeOwing"
        assert body["outstanding"]["fail_closed"] is True
        assert body["sj_coverage"]["list_endpoint"]
        assert body["sj_coverage"]["full_accurate_sj_universe"] is False
        assert body["sj_coverage"]["atomic_snapshot_guaranteed"] is False
        assert body["sj_coverage"]["fail_closed"] is True
