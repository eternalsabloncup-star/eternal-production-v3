"""Fase 1B: PostgreSQL Jadwal Produksi read API — isolated test DB only."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.db_url_guard import resolve_test_database_urls

_async_url, _sync_url = resolve_test_database_urls()
os.environ["DATABASE_URL"] = _async_url
os.environ["DATABASE_URL_SYNC"] = _sync_url
os.environ["APP_ENV"] = "test"
os.environ["V3_JWT_SECRET"] = "v3_test_jwt_secret_not_from_v1"
os.environ["V3_PASSWORD_PEPPER"] = "v3_test_password_pepper_distinct"
os.environ["V3_WORKFLOW_AUTHORIZATION"] = "legacy"

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import dispose_engine, get_engine, get_session_factory
from app.main import create_app
from app.models.production.event import ProductionEvent
from app.models.production.job import ProductionJob
from app.models.production.prep import JobLineQty
from app.models.production.schedule import ScheduleAssignment
from app.models.user import User
from app.services.production import permissions as P

get_settings.cache_clear()

PERMS = [P.JOB_READ, P.JOB_CREATE, P.SCHEDULE_MANAGE]


@pytest.fixture
async def client():
    await dispose_engine()
    get_settings.cache_clear()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            User(
                username="sched.lead",
                display_name="Schedule Lead",
                role="kepala_produksi",
                password_hash=hash_password("secret-pass"),
                permissions=PERMS,
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="sched.other",
                display_name="Other Branch",
                role="operator",
                password_hash=hash_password("secret-pass"),
                permissions=[P.JOB_READ],
                branch_ids=["branch-b"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="sched.noperm",
                display_name="No Perm",
                role="operator",
                password_hash=hash_password("secret-pass"),
                permissions=[],
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        await session.commit()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login = await ac.post(
            "/api/v1/auth/login",
            json={"username": "sched.lead", "password": "secret-pass"},
        )
        assert login.status_code == 200, login.text
        ac.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        yield ac
    await dispose_engine()
    get_settings.cache_clear()


async def _seed_core(session):
    """PO outside any inbox page: print + non_print + unknown + multi-op + hold."""
    j_out = ProductionJob(
        accurate_so_number="SO/SCHED/OUTSIDE-PAGE",
        branch_id="branch-a",
        customer_name="Cust Outside",
        design_status="approved",
        payment_status="approved",
        processing_status="Terproses",
    )
    j_mix = ProductionJob(
        accurate_so_number="SO/SCHED/MIXED",
        branch_id="branch-a",
        customer_name="Cust Mixed",
        design_status="approved",
        payment_status="approved",
    )
    j_np = ProductionJob(
        accurate_so_number="SO/SCHED/NONPRINT",
        branch_id="branch-a",
        customer_name="Cust NonPrint",
        design_status="approved",
        payment_status="approved",
    )
    j_hold = ProductionJob(
        accurate_so_number="SO/SCHED/HOLD",
        branch_id="branch-a",
        customer_name="Cust Hold",
        design_status="approved",
        payment_status="approved",
    )
    j_b = ProductionJob(
        accurate_so_number="SO/SCHED/BRANCH-B",
        branch_id="branch-b",
        customer_name="Other Branch Cust",
        design_status="approved",
        payment_status="approved",
    )
    session.add_all([j_out, j_mix, j_np, j_hold, j_b])
    await session.flush()
    session.add_all(
        [
            JobLineQty(job_id=j_out.id, so_line_id="L1", accurate_item_id="10", po_qty=Decimal("3000"), production_process="print"),
            JobLineQty(job_id=j_mix.id, so_line_id="L-PRINT", accurate_item_id="20", po_qty=Decimal("3000"), production_process="print"),
            JobLineQty(job_id=j_mix.id, so_line_id="L-LID", accurate_item_id="21", po_qty=Decimal("3000"), production_process="non_print"),
            JobLineQty(job_id=j_mix.id, so_line_id="L-UNK", accurate_item_id="22", po_qty=Decimal("500"), production_process="unknown"),
            JobLineQty(job_id=j_np.id, so_line_id="L-NP", accurate_item_id="30", po_qty=Decimal("1000"), production_process="non_print"),
            JobLineQty(
                job_id=j_hold.id,
                so_line_id="L-HOLD",
                accurate_item_id="40",
                po_qty=Decimal("2000"),
                production_process="print",
                source_qty=Decimal("1800"),
            ),
            JobLineQty(job_id=j_b.id, so_line_id="L-B", accurate_item_id="50", po_qty=Decimal("100"), production_process="print"),
        ]
    )
    # Unassigned print on outside-page; dual operators on mixed print line.
    session.add_all(
        [
            ScheduleAssignment(
                job_id=j_mix.id,
                so_line_id="L-PRINT",
                color_pass=1,
                operator_name="Operator A",
                machine_name="SA-1",
                work_date=date(2026, 11, 10),
                branch_id="branch-a",
                qty_planned=Decimal("1500"),
                created_by=1,
            ),
            ScheduleAssignment(
                job_id=j_mix.id,
                so_line_id="L-PRINT",
                color_pass=1,
                operator_name="Operator B",
                machine_name="SA-2",
                work_date=date(2026, 11, 11),
                branch_id="branch-a",
                qty_planned=Decimal("1500"),
                sequence_no=2,
                created_by=1,
            ),
        ]
    )
    session.add(
        ProductionEvent(
            job_id=j_mix.id,
            event_type="output_confirmed",
            so_line_id="L-PRINT",
            color_pass=1,
            qty_physical=Decimal("400"),
            actor_user_id=1,
            idempotency_key="sched-out-1",
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_print_outside_inbox_page_appears(client):
    factory = get_session_factory()
    async with factory() as session:
        await _seed_core(session)

    r = await client.get("/api/v1/production/ops/schedule?page=1&page_size=10")
    assert r.status_code == 200, r.text
    body = r.json()
    sos = {i["accurate_so_number"] for i in body["items"]}
    assert "SO/SCHED/OUTSIDE-PAGE" in sos
    assert body["source"] == "postgresql_job_line_qtys"
    assert body["incomplete"] is False


@pytest.mark.asyncio
async def test_unassigned_print_in_belum_dijadwalkan(client):
    factory = get_session_factory()
    async with factory() as session:
        await _seed_core(session)

    r = await client.get("/api/v1/production/ops/schedule?bucket=belum_dijadwalkan")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert any(i["accurate_so_number"] == "SO/SCHED/OUTSIDE-PAGE" and i["row_kind"] == "unassigned" for i in items)
    assert all(i["row_kind"] == "unassigned" for i in items)


@pytest.mark.asyncio
async def test_mixed_po_only_print_lines(client):
    factory = get_session_factory()
    async with factory() as session:
        await _seed_core(session)

    r = await client.get("/api/v1/production/ops/schedule?q=SO/SCHED/MIXED")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items
    assert all(i["production_process"] == "print" for i in items)
    assert all(i["so_line_id"] == "L-PRINT" for i in items)
    assert len(items) == 2  # two operators


@pytest.mark.asyncio
async def test_nonprint_po_excluded(client):
    factory = get_session_factory()
    async with factory() as session:
        await _seed_core(session)

    r = await client.get("/api/v1/production/ops/schedule?q=NONPRINT")
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []


@pytest.mark.asyncio
async def test_dual_operator_rows_and_qty_not_duplicated(client):
    factory = get_session_factory()
    async with factory() as session:
        await _seed_core(session)

    r = await client.get("/api/v1/production/ops/schedule?q=MIXED&bucket=dijadwalkan")
    assert r.status_code == 200, r.text
    body = r.json()
    items = body["items"]
    assert len(items) == 2
    ops = {i["operator_name"] for i in items}
    assert ops == {"Operator A", "Operator B"}
    # Line qty fields identical; summary must not double print qty.
    assert items[0]["qty_print_po"] == "3000.000" or items[0]["qty_print_po"] == "3000"
    assert Decimal(items[0]["qty_allocated"]) == Decimal("3000")
    assert Decimal(body["summary"]["qty_print_po"]) == Decimal("3000")
    assert Decimal(body["summary"]["qty_allocated"]) == Decimal("3000")
    assert Decimal(body["summary"]["qty_printed_done"]) == Decimal("400")


@pytest.mark.asyncio
async def test_hold_bucket_and_unknown_excluded_from_totals(client):
    factory = get_session_factory()
    async with factory() as session:
        await _seed_core(session)

    hold = await client.get("/api/v1/production/ops/schedule?bucket=hold")
    assert hold.status_code == 200, hold.text
    hold_items = hold.json()["items"]
    assert any(i["accurate_so_number"] == "SO/SCHED/HOLD" and i["hold"] for i in hold_items)

    all_rows = await client.get("/api/v1/production/ops/schedule")
    body = all_rows.json()
    assert body["unverified"]["unknown_print_candidate_lines"] >= 1
    # UNKNOWN line qty 500 must not appear in print summary.
    assert Decimal(body["summary"]["qty_print_po"]) == Decimal("3000") + Decimal("3000") + Decimal("2000")


@pytest.mark.asyncio
async def test_pagination_preserves_total_and_all_print_rows(client):
    factory = get_session_factory()
    async with factory() as session:
        await _seed_core(session)

    p1 = await client.get("/api/v1/production/ops/schedule?page=1&page_size=2")
    p2 = await client.get("/api/v1/production/ops/schedule?page=2&page_size=2")
    assert p1.status_code == 200 and p2.status_code == 200
    b1, b2 = p1.json(), p2.json()
    assert b1["total"] == b2["total"]
    assert b1["total"] >= 4
    assert len(b1["items"]) == 2
    keys = {i["row_key"] for i in b1["items"]} | {i["row_key"] for i in b2["items"]}
    assert len(keys) >= 4


@pytest.mark.asyncio
async def test_work_date_filter_keeps_unassigned(client):
    factory = get_session_factory()
    async with factory() as session:
        await _seed_core(session)

    r = await client.get(
        "/api/v1/production/ops/schedule?date_from=2026-11-10&date_to=2026-11-10&bucket=semua"
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    # Operator A on 11-10 kept; Operator B on 11-11 filtered out; unassigned outside-page kept.
    assert any(i["operator_name"] == "Operator A" for i in items)
    assert not any(i["operator_name"] == "Operator B" for i in items)
    assert any(i["accurate_so_number"] == "SO/SCHED/OUTSIDE-PAGE" for i in items)


@pytest.mark.asyncio
async def test_branch_scope_and_403(client):
    factory = get_session_factory()
    async with factory() as session:
        await _seed_core(session)

    # branch-a user must not see branch-b print line
    r = await client.get("/api/v1/production/ops/schedule")
    assert r.status_code == 200
    assert all(i["branch_id"] == "branch-a" for i in r.json()["items"])

    other = await client.post(
        "/api/v1/auth/login",
        json={"username": "sched.other", "password": "secret-pass"},
    )
    assert other.status_code == 200
    r2 = await client.get(
        "/api/v1/production/ops/schedule",
        headers={"Authorization": f"Bearer {other.json()['access_token']}"},
    )
    assert r2.status_code == 200
    assert all(i["branch_id"] == "branch-b" for i in r2.json()["items"])

    noperm = await client.post(
        "/api/v1/auth/login",
        json={"username": "sched.noperm", "password": "secret-pass"},
    )
    assert noperm.status_code == 200
    denied = await client.get(
        "/api/v1/production/ops/schedule",
        headers={"Authorization": f"Bearer {noperm.json()['access_token']}"},
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_cancelled_jobs_not_supported_flag(client):
    factory = get_session_factory()
    async with factory() as session:
        await _seed_core(session)
    r = await client.get("/api/v1/production/ops/schedule")
    assert r.status_code == 200
    assert r.json()["cancelled_jobs_supported"] is False


@pytest.mark.asyncio
async def test_search_by_operator(client):
    factory = get_session_factory()
    async with factory() as session:
        await _seed_core(session)
    r = await client.get("/api/v1/production/ops/schedule?q=Operator%20B")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items
    assert all(
        i["accurate_so_number"] == "SO/SCHED/MIXED" for i in items
    )
