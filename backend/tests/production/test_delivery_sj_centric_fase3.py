"""Fase 3 — Jadwal Pengiriman satu baris per SJ + detail multi-item."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.production.sj_line_helpers import loading_body
from tests.production.test_multi_sj_loading import _login, _seed_packed, client  # noqa: F401

J = "/api/v1/production/jobs"
O = "/api/v1/production/ops"


@pytest.mark.asyncio
async def test_deliveries_one_row_per_sj_with_items_and_detail(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "10")])
    load = await client.post(
        f"{J}/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="10",
            idempotency_key="f3-sj-load-1",
            accurate_sj_number="DO/F3/0001",
        ),
    )
    assert load.status_code == 200, load.text
    listed = (await client.get(f"{O}/deliveries", headers=h)).json()
    assert listed["coverage"]["accurate_write_on_view"] is False
    rows = listed["items"]
    assert len(rows) == 1
    row = rows[0]
    assert row["sj_id"] == row["accurate_sj_id"] == "SJ1"
    assert row["sj_number"] == "DO/F3/0001" or row["accurate_sj_number"]
    assert row["item_count"] >= 1
    assert isinstance(row["items"], list) and len(row["items"]) >= 1
    assert row["items"][0]["accurate_sj_line_id"] == "SL1"
    assert row["field_availability"]["address"] == "BELUM TERSEDIA"
    assert row["zone"] is None and row["expedition"] is None
    # No duplicate when listing again
    again = (await client.get(f"{O}/deliveries", headers=h)).json()["items"]
    assert len(again) == 1
    detail = await client.get(f"{O}/deliveries/SJ1", headers=h)
    assert detail.status_code == 200, detail.text
    body = detail.json()["item"]
    assert body["accurate_sj_id"] == "SJ1"
    assert len(body["items"]) >= 1
    miss = await client.get(f"{O}/deliveries/SJ-NOPE", headers=h)
    assert miss.status_code == 404
    hit = (await client.get(f"{O}/deliveries?q=DO/F3", headers=h)).json()["items"]
    assert any(r["accurate_sj_id"] == "SJ1" for r in hit)
