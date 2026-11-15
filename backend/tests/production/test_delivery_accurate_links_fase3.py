"""Fase 3 — inventaris SJ via SO Accurate links (bukan list-all)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import get_session_factory
from app.models.production.job import ProductionJob
from app.models.user import User
from app.services.production import operations as ops
from tests.production.sj_line_helpers import loading_body
from tests.production.test_multi_sj_loading import _login, _seed_packed, client  # noqa: F401

J = "/api/v1/production/jobs"
O = "/api/v1/production/ops"


@pytest.mark.asyncio
async def test_coverage_documents_missing_sj_list_endpoint(client: AsyncClient):
    h = await _login(client)
    body = (await client.get(f"{O}/deliveries", headers=h)).json()
    assert body["coverage"]["accurate_sj_list_endpoint"] is None
    assert body["coverage"]["accurate_write_on_view"] is False
    assert "list-all" in body["coverage"]["source"]


@pytest.mark.asyncio
async def test_include_accurate_links_adds_linked_sj_without_duplicate(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "10")])
    assert (
        await client.post(
            f"{J}/{jid}/loading",
            headers=h,
            json=loading_body(
                accurate_sj_id="SJ1",
                accurate_sj_line_id="SL1",
                so_line_id="L1",
                qty_physical="5",
                idempotency_key="f3-link-load-1",
            ),
        )
    ).status_code == 200

    class GW:
        async def get(self, path, **kwargs):
            if path.startswith("/sales-orders/"):
                return {
                    "links": {
                        "delivery_note_ids": ["SJ1", "SJ-LINK-ONLY"],
                        "delivery_notes_present": True,
                        "evidence_authority": False,
                    },
                }
            if "SJ-LINK-ONLY" in path:
                return {
                    "id": "SJ-LINK-ONLY",
                    "number": "DO/LINK/1",
                    "status": "DELIVERED",
                    "cancelled": False,
                    "verifiable": True,
                    "sales_order_number": "SO-X",
                    "customer": {"name": "PT Link"},
                    "branch": {"id": "branch-a"},
                    "address": "Jl. Uji 1",
                    "zone": "JS",
                    "expedition": "OUTLET",
                    "remarks": "CATATAN",
                    "line_items": [
                        {
                            "accurate_sj_line_id": "LL1",
                            "so_line_id": "L1",
                            "sku": "100329",
                            "quantity": 100,
                            "uom": "PCS",
                        }
                    ],
                }
            raise AssertionError(path)

    async with get_session_factory()() as session:
        user = (
            await session.scalars(select(User).where(User.username == "msj.lead"))
        ).first()
        listed = await ops.list_deliveries(
            session,
            user,
            include_accurate_links=True,
            gateway=GW(),
            page_size=50,
        )
    ids = [r["accurate_sj_id"] for r in listed["items"]]
    assert ids.count("SJ1") == 1
    assert "SJ-LINK-ONLY" in ids
    link_row = next(r for r in listed["items"] if r["accurate_sj_id"] == "SJ-LINK-ONLY")
    assert link_row["inventory_source"] == "accurate_so_link"
    assert link_row["zone"] == "JS"
    assert link_row["expedition"] == "OUTLET"
    assert link_row["address"] == "Jl. Uji 1"
    assert listed["coverage"]["include_accurate_links"] is True
    assert listed["coverage"]["accurate_sj_list_endpoint"] is None
