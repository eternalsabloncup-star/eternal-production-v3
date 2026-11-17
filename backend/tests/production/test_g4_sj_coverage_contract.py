"""G4 — deliveries coverage contract (COVERAGE TERBATAS, fail-closed)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.production.test_multi_sj_loading import _login, client  # noqa: F401

O = "/api/v1/production/ops"


@pytest.mark.asyncio
async def test_deliveries_coverage_declares_limited_sj_strategy(client: AsyncClient):
    h = await _login(client)
    body = (await client.get(f"{O}/deliveries", headers=h)).json()
    cov = body["coverage"]
    assert cov["accurate_sj_list_endpoint"] == (
        "GET /delivery-notes → delivery-order/list.do"
    )
    assert cov["full_accurate_sj_universe"] is False
    assert cov["live_sj_list_verified"] is True
    assert cov["census_scan_pass_director"] is True
    assert cov["atomic_snapshot_guaranteed"] is False
    assert cov["fail_closed"] is True
    assert cov["coverage_label"] == "LIST_PROVEN_ATOMIC_NOT_GUARANTEED"
    assert cov["sj_detail_lookup_prefers_internal_id"] is True
    assert "accurate_delivery_order_list_do" in cov["sj_discovery_strategy"]
    assert "detail_do_by_internal_id" in cov["sj_discovery_strategy"]
    assert "v3_loading_events" in cov["sj_discovery_strategy"]
    assert "so_links_delivery_note_ids" in cov["sj_discovery_strategy"]
    assert cov["sj_without_so_relation"] == (
        "delivery_order_list_or_v3_loading_by_internal_id"
    )
    assert cov["accurate_write_on_view"] is False
