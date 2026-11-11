"""Focused Phase 2.1 screener/helper + payroll tests."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

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
from app.models.user import User
from app.services.production import permissions as P

get_settings.cache_clear()

ALL_PERMS = [
    P.JOB_CREATE,
    P.JOB_READ,
    P.DESIGN_UPLOAD,
    P.DESIGN_APPROVE,
    P.DESIGN_BYPASS,
    P.PAYMENT_RECORD,
    P.PAYMENT_BYPASS,
    P.SCHEDULE_MANAGE,
    P.PREP_SCREENER,
    P.PREP_HELPER,
    P.SAMPLE_UPLOAD,
    P.SAMPLE_DECIDE,
    P.OUTPUT_CONFIRM,
    P.REJECT_RECORD,
    P.REJECT_VERIFY,
    P.PAYROLL_MANAGE,
    P.PAYROLL_READ,
    P.TRACKING_READ,
]


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
                username="prod.lead",
                display_name="Prod Lead",
                role="kepala_produksi",
                password_hash=hash_password("secret-pass"),
                permissions=ALL_PERMS,
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        await session.commit()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await dispose_engine()
    get_settings.cache_clear()


async def _auth(client: AsyncClient) -> dict:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "prod.lead", "password": "secret-pass"},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _ready_job(client: AsyncClient, h: dict, so: str) -> tuple[int, int]:
    job = (
        await client.post(
            "/api/v1/production/jobs",
            headers=h,
            json={"accurate_so_number": so, "branch_id": "branch-a"},
        )
    ).json()
    job_id = job["id"]
    d = (
        await client.post(
            f"/api/v1/production/jobs/{job_id}/design/versions",
            headers=h,
            json={"file_name": "a.pdf", "storage_key": "a"},
        )
    ).json()
    await client.post(
        f"/api/v1/production/jobs/design/versions/{d['id']}/decision",
        headers=h,
        json={"decision": "approved", "bypass": True, "reason": "owner"},
    )
    await client.post(
        f"/api/v1/production/jobs/{job_id}/payment/bypass",
        headers=h,
        json={"reason": "authorized bypass"},
    )
    asg = (
        await client.post(
            f"/api/v1/production/jobs/{job_id}/schedule/assignments",
            headers=h,
            json={
                "so_line_id": "line-1",
                "color_pass": 1,
                "operator_name": "Rizki",
                "machine_name": "Semi Auto 01",
                "work_date": str(date.today()),
                "qty_planned": "50",
            },
        )
    ).json()
    return job_id, asg["id"]


@pytest.mark.asyncio
async def test_helper_qty_guards_and_idempotency(client: AsyncClient) -> None:
    h = await _auth(client)
    job_id, asg_id = await _ready_job(client, h, "SO/PREP/001")

    over = await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/helper",
        headers=h,
        json={
            "so_line_id": "line-1",
            "qty": "60",
            "po_qty": "50",
            "evidence_ref": "e1",
            "idempotency_key": "helper-over-1",
        },
    )
    assert over.status_code == 409

    ok = await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/helper",
        headers=h,
        json={
            "so_line_id": "line-1",
            "qty": "40",
            "po_qty": "50",
            "evidence_ref": "e1",
            "idempotency_key": "helper-ok-1",
            "assignment_id": asg_id,
        },
    )
    assert ok.status_code == 200
    dup = await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/helper",
        headers=h,
        json={
            "so_line_id": "line-1",
            "qty": "41",
            "po_qty": "50",
            "evidence_ref": "e2",
            "idempotency_key": "helper-ok-1",
        },
    )
    assert dup.status_code == 409

    await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/screener",
        headers=h,
        json={
            "so_line_id": "line-1",
            "qty": "1",
            "evidence_ref": "s1",
            "idempotency_key": "screen-ok-1",
            "assignment_id": asg_id,
        },
    )
    # Output beyond prepared blocked
    out = await client.post(
        f"/api/v1/production/jobs/{job_id}/outputs",
        headers=h,
        json={
            "assignment_id": asg_id,
            "qty_physical": "41",
            "idempotency_key": "out-over-prep",
        },
    )
    assert out.status_code == 409


@pytest.mark.asyncio
async def test_payroll_rate_history_and_no_duplicate_wages(
    client: AsyncClient,
) -> None:
    h = await _auth(client)
    job_id, asg_id = await _ready_job(client, h, "SO/PAY/001")
    await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/screener",
        headers=h,
        json={
            "so_line_id": "line-1",
            "qty": "1",
            "evidence_ref": "s1",
            "idempotency_key": "pay-screen-1",
            "assignment_id": asg_id,
        },
    )
    await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/helper",
        headers=h,
        json={
            "so_line_id": "line-1",
            "qty": "30",
            "po_qty": "50",
            "evidence_ref": "h1",
            "idempotency_key": "pay-helper-1",
            "assignment_id": asg_id,
        },
    )
    out = await client.post(
        f"/api/v1/production/jobs/{job_id}/outputs",
        headers=h,
        json={
            "assignment_id": asg_id,
            "qty_physical": "20",
            "color_pass": 1,
            "idempotency_key": "pay-out-1",
        },
    )
    assert out.status_code == 200

    r1 = await client.post(
        "/api/v1/production/payroll/rates",
        headers=h,
        json={
            "component": "one",
            "amount": "10",
            "effective_from": "2020-01-01",
        },
    )
    assert r1.status_code == 200
    r2 = await client.post(
        "/api/v1/production/payroll/rates",
        headers=h,
        json={
            "component": "one",
            "amount": "25",
            "effective_from": str(date.today()),
            "note": "new rate",
        },
    )
    assert r2.status_code == 200
    rates = await client.get(
        f"/api/v1/production/payroll/rates?on_date={date.today()}", headers=h
    )
    assert rates.status_code == 200
    assert Decimal(rates.json()["one"]) == Decimal("25")

    run = await client.post(
        "/api/v1/production/payroll/runs",
        headers=h,
        json={
            "period_start": str(date.today()),
            "period_end": str(date.today()),
            "idempotency_key": "payroll-run-1",
            "branch_id": "branch-a",
        },
    )
    assert run.status_code == 200
    run_id = run.json()["id"]
    # Idempotent recompute returns same run (no duplicate wages)
    again = await client.post(
        "/api/v1/production/payroll/runs",
        headers=h,
        json={
            "period_start": str(date.today()),
            "period_end": str(date.today()),
            "idempotency_key": "payroll-run-1",
            "branch_id": "branch-a",
        },
    )
    assert again.json()["id"] == run_id
    detail = await client.get(
        f"/api/v1/production/payroll/runs/{run_id}", headers=h
    )
    assert detail.status_code == 200
    lines = detail.json()["lines"]
    assert len(lines) == 1
    assert lines[0]["operator_name"] == "Rizki"
    assert Decimal(lines[0]["qty_one"]) == Decimal("20")
    assert Decimal(lines[0]["amount_gross"]) == Decimal("500.00")  # 20 * 25


@pytest.mark.asyncio
async def test_by_so_lookup_is_read_only(client: AsyncClient) -> None:
    h = await _auth(client)
    missing = await client.get(
        "/api/v1/production/jobs/by-so/SO/MISSING/001", headers=h
    )
    assert missing.status_code == 404
    job_id, _ = await _ready_job(client, h, "SO/LOOKUP/001")
    found = await client.get(
        "/api/v1/production/jobs/by-so/SO/LOOKUP/001", headers=h
    )
    assert found.status_code == 200
    assert found.json()["id"] == job_id
    board = await client.get(
        f"/api/v1/production/jobs/{job_id}/board", headers=h
    )
    assert board.status_code == 200
    assert board.json()["job"]["id"] == job_id
    assert "design_versions" in board.json()
    assert "events" in board.json()
