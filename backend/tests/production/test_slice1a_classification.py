"""Slice 1A: persist Accurate line id + nullable classifications; gates unchanged."""

from __future__ import annotations

import os
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

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import dispose_engine, get_engine, get_session_factory
from app.main import create_app
from app.models.production.job import ProductionJob
from app.models.production.prep import JobLineQty
from app.models.user import User
from app.services.production import permissions as P
from app.services.production.engine import gates_open_for_schedule
from app.services.production.prep import sync_job_lines_from_so_detail

get_settings.cache_clear()

PERMS = [P.JOB_CREATE, P.JOB_READ, P.DESIGN_UPLOAD, P.PAYMENT_RECORD, P.SCHEDULE_MANAGE]


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
                username="slice1a.lead",
                display_name="Slice1A Lead",
                role="kepala_produksi",
                password_hash=hash_password("secret-pass"),
                permissions=PERMS,
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
            json={"username": "slice1a.lead", "password": "secret-pass"},
        )
        assert login.status_code == 200
        ac.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        yield ac
    await dispose_engine()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_unknown_classification_remains_unknown_after_sync(client):
    r = await client.post(
        "/api/v1/production/jobs",
        json={
            "accurate_so_number": "SO/1A/001",
            "branch_id": "branch-a",
            "accurate_id": "823001",
            "customer_name": "Cust",
            "buffer_stock": None,
            "urgent_state": None,
            "line_items": [
                {
                    "accurate_line_id": "556677",
                    "accurate_item_id": "88",
                    "quantity": 100,
                    "production_process": "unknown",
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["buffer_stock"] is None
    assert body["urgent_state"] is None

    board = await client.get(f"/api/v1/production/jobs/{body['id']}/board")
    assert board.status_code == 200
    lines = board.json()["job_lines"]
    assert len(lines) == 1
    assert lines[0]["so_line_id"] == "556677"
    assert lines[0]["accurate_item_id"] == "88"
    assert lines[0]["production_process"] == "unknown"
    assert board.json()["job"]["buffer_stock"] is None
    assert board.json()["job"]["urgent_state"] is None


@pytest.mark.asyncio
async def test_accurate_line_id_survives_and_mixed_lines(client):
    r = await client.post(
        "/api/v1/production/jobs",
        json={
            "accurate_so_number": "SO/1A/MIX",
            "branch_id": "branch-a",
            "accurate_id": "9",
            "line_items": [
                {
                    "accurate_line_id": "101",
                    "quantity": 10,
                    "production_process": "print",
                },
                {
                    "accurate_line_id": "102",
                    "quantity": 20,
                    "production_process": "non_print",
                },
                {
                    "accurate_line_id": "103",
                    "quantity": 30,
                    "production_process": "unknown",
                },
            ],
        },
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]
    board = await client.get(f"/api/v1/production/jobs/{job_id}/board")
    by_id = {ln["so_line_id"]: ln for ln in board.json()["job_lines"]}
    assert by_id["101"]["production_process"] == "print"
    assert by_id["102"]["production_process"] == "non_print"
    assert by_id["103"]["production_process"] == "unknown"


@pytest.mark.asyncio
async def test_idempotent_resync_keeps_line_identity(client):
    payload = {
        "accurate_so_number": "SO/1A/IDEMP",
        "branch_id": "branch-a",
        "accurate_id": "11",
        "line_items": [
            {
                "accurate_line_id": "777",
                "accurate_item_id": "5",
                "quantity": 50,
                "production_process": "unknown",
            }
        ],
    }
    first = await client.post("/api/v1/production/jobs", json=payload)
    assert first.status_code == 200
    second = await client.post("/api/v1/production/jobs", json=payload)
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.scalars(
                select(JobLineQty).where(JobLineQty.job_id == first.json()["id"])
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].so_line_id == "777"
        assert rows[0].production_process == "unknown"
        assert rows[0].po_qty == Decimal("50")


@pytest.mark.asyncio
async def test_no_false_buffer_urgent_on_create(client):
    r = await client.post(
        "/api/v1/production/jobs",
        json={
            "accurate_so_number": "SO/1A/NOFALSE",
            "branch_id": "branch-a",
        },
    )
    assert r.status_code == 200
    assert r.json()["buffer_stock"] is None
    assert r.json()["urgent_state"] is None

    factory = get_session_factory()
    async with factory() as session:
        job = await session.scalar(
            select(ProductionJob).where(
                ProductionJob.accurate_so_number == "SO/1A/NOFALSE"
            )
        )
        assert job is not None
        assert job.buffer_stock is None
        assert job.urgent_state is None


@pytest.mark.asyncio
async def test_design_payment_gates_independent_of_classification():
    job = ProductionJob(
        accurate_so_number="SO/GATE/1",
        branch_id="branch-a",
        buffer_stock=None,
        urgent_state=None,
        design_status="pending",
        payment_status="pending",
    )
    with pytest.raises(Exception) as exc:
        await gates_open_for_schedule(job)
    assert "Design" in str(exc.value.detail)

    job.design_status = "approved"
    with pytest.raises(Exception) as exc2:
        await gates_open_for_schedule(job)
    assert "Payment" in str(exc2.value.detail)

    job.payment_status = "approved"
    await gates_open_for_schedule(job)


@pytest.mark.asyncio
async def test_sync_helper_does_not_invent_print_from_missing_field():
    await dispose_engine()
    get_settings.cache_clear()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = get_session_factory()
    async with factory() as session:
        job = ProductionJob(
            accurate_so_number="SO/SYNC/1",
            branch_id="branch-a",
            processing_status="Baru",
        )
        session.add(job)
        await session.flush()
        synced = await sync_job_lines_from_so_detail(
            session,
            job,
            [
                {"accurate_line_id": "1", "quantity": 3},
                {
                    "accurate_line_id": "2",
                    "quantity": 4,
                    "production_process": "non_print",
                },
            ],
        )
        await session.commit()
        assert synced[0].production_process == "unknown"
        assert synced[1].production_process == "non_print"
    await dispose_engine()
