"""Slice 1H — official team-task derivation + schedule gates (no migration)."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

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
from app.models.production.job import ProductionJob
from app.models.user import User
from app.services.production import permissions as P
from app.services.production.engine import (
    derive_team_tasks_for_job,
    gates_open_for_schedule,
)

get_settings.cache_clear()

ALL_PERMS = [
    P.JOB_CREATE,
    P.JOB_READ,
    P.DESIGN_UPLOAD,
    P.DESIGN_APPROVE,
    P.DESIGN_BYPASS,
    P.PAYMENT_RECORD,
    P.PAYMENT_BYPASS,
    P.PAYMENT_REVOKE,
    P.SCHEDULE_MANAGE,
    P.PREP_SCREENER,
    P.PREP_HELPER,
    P.SAMPLE_UPLOAD,
    P.SAMPLE_DECIDE,
    P.OUTPUT_CONFIRM,
    P.REJECT_RECORD,
    P.REJECT_VERIFY,
    P.PACKING_RECORD,
    P.DELIVERY_MANAGE,
    P.TRACKING_READ,
]


def _job(**kwargs):
    defaults = dict(
        id=1,
        accurate_so_number="SO/1H/001",
        branch_id="branch-a",
        customer_name="Acme",
        design_status="pending",
        payment_status="pending",
        processing_status="Baru",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _states(tasks):
    return {t["kind"]: t["state"] for t in tasks}


def test_upload_design_without_payment_for_print():
    job = _job()
    lines = [SimpleNamespace(production_process="print")]
    tasks = derive_team_tasks_for_job(
        job, lines=lines, designs=[], assignments=[], prep_states=[], samples=[], events=[]
    )
    s = _states(tasks)
    assert s["design_upload"] == "actionable"
    assert s["design_approve"] == "blocked"
    assert "schedule" not in s  # payment not open → not visible


def test_approval_never_auto_on_upload():
    job = _job()
    lines = [SimpleNamespace(production_process="print")]
    designs = [SimpleNamespace(status="pending")]
    tasks = derive_team_tasks_for_job(
        job,
        lines=lines,
        designs=designs,
        assignments=[],
        prep_states=[],
        samples=[],
        events=[],
    )
    s = _states(tasks)
    assert s["design_upload"] == "done"
    assert s["design_approve"] == "actionable"


def test_schedule_siap_when_payment_ok_save_still_needs_design():
    job = _job(payment_status="approved", design_status="pending")
    lines = [SimpleNamespace(production_process="print")]
    designs = [SimpleNamespace(status="pending")]
    tasks = derive_team_tasks_for_job(
        job,
        lines=lines,
        designs=designs,
        assignments=[],
        prep_states=[],
        samples=[],
        events=[],
    )
    s = _states(tasks)
    assert s["schedule"] == "actionable"
    assert "screen" not in s
    assert "prepare" not in s
    sched = next(t for t in tasks if t["kind"] == "schedule")
    assert "Design" in (sched.get("reason") or "")


def test_screen_prepare_only_after_schedule_parallel():
    job = _job(payment_status="approved", design_status="approved")
    lines = [SimpleNamespace(production_process="print")]
    assignments = [SimpleNamespace(status="active")]
    tasks = derive_team_tasks_for_job(
        job,
        lines=lines,
        designs=[SimpleNamespace(status="approved")],
        assignments=assignments,
        prep_states=[],
        samples=[],
        events=[],
    )
    s = _states(tasks)
    assert s["schedule"] == "done"
    assert s["screen"] == "actionable"
    assert s["prepare"] == "actionable"
    assert "sample" not in s  # no prep evidence yet


def test_non_print_no_fake_screen_sample_print():
    job = _job(payment_status="approved")
    lines = [SimpleNamespace(production_process="non_print")]
    tasks = derive_team_tasks_for_job(
        job, lines=lines, designs=[], assignments=[], prep_states=[], samples=[], events=[]
    )
    kinds = {t["kind"] for t in tasks}
    assert "screen" not in kinds
    assert "sample" not in kinds
    assert "print" not in kinds
    assert "design_upload" not in kinds
    assert "stockprep" not in kinds
    assert "schedule" not in kinds
    assert _states(tasks)["stockpack"] == "actionable"


def test_payment_not_guessed_from_terproses():
    job = _job(processing_status="Terproses", payment_status="pending")
    lines = [SimpleNamespace(production_process="print")]
    tasks = derive_team_tasks_for_job(
        job, lines=lines, designs=[], assignments=[], prep_states=[], samples=[], events=[]
    )
    assert "schedule" not in _states(tasks)


def test_unknown_process_no_print_chain():
    job = _job()
    lines = [SimpleNamespace(production_process="unknown")]
    tasks = derive_team_tasks_for_job(
        job, lines=lines, designs=[], assignments=[], prep_states=[], samples=[], events=[]
    )
    kinds = {t["kind"] for t in tasks}
    assert kinds == set()
    assert "screen" not in kinds
    assert "prepare" not in kinds
    assert "design_upload" not in kinds


@pytest.mark.asyncio
async def test_gates_skip_design_for_non_print_only_with_session():
    await dispose_engine()
    get_settings.cache_clear()
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = get_session_factory()
    async with factory() as session:
        job = ProductionJob(
            accurate_so_number="SO/1H/NONPRINT",
            branch_id="branch-a",
            design_status="pending",
            payment_status="approved",
        )
        session.add(job)
        await session.flush()
        from app.services.production.prep import upsert_job_line_qty

        await upsert_job_line_qty(
            session,
            job,
            so_line_id="L1",
            po_qty=Decimal("10"),
            production_process="non_print",
        )
        await session.commit()
        await session.refresh(job)
        # Without session → still requires design (fail closed)
        with pytest.raises(Exception) as exc:
            await gates_open_for_schedule(job)
        assert "Design" in str(exc.value.detail)
        # Explicit active bypass, not the stale payment mirror, opens payment.
        from app.models.production.payment import PaymentBypass
        session.add(PaymentBypass(job_id=job.id, reason="Non-print test authorization", authorized_by=1, active=True))
        await session.flush()
        # With session → non-print-only skips design
        await gates_open_for_schedule(job, session)


@pytest.fixture
async def client():
    await dispose_engine()
    get_settings.cache_clear()
    eng = get_engine()
    async with eng.begin() as conn:
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
        login = await ac.post(
            "/api/v1/auth/login",
            json={"username": "prod.lead", "password": "secret-pass"},
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac
    await dispose_engine()


@pytest.mark.asyncio
async def test_tasks_api_and_sync_ensure(client: AsyncClient) -> None:
    # Sync ensure creates job + print line → upload design actionable
    resp = await client.post(
        "/api/v1/production/jobs/tasks",
        json={
            "sync_ensure": True,
            "so_numbers": ["SO/1H/API"],
            "jobs": [
                {
                    "accurate_so_number": "SO/1H/API",
                    "branch_id": "branch-a",
                    "customer_name": "Renea",
                    "line_items": [
                        {
                            "accurate_line_id": "L1",
                            "quantity": "100",
                            "production_process": "print",
                        }
                    ],
                }
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "v3_official"
    assert "SO/1H/API" in body["synced_so_numbers"]
    kinds = {t["kind"]: t["state"] for t in body["tasks"]}
    assert kinds["design_upload"] == "actionable"
    assert kinds["design_approve"] == "blocked"
    assert "schedule" not in kinds

    # Upload design → approval actionable; payment still closed
    job_id = body["jobs"][0]["id"]
    up = await client.post(
        f"/api/v1/production/jobs/{job_id}/design/versions",
        json={"file_name": "a.pdf", "storage_key": "designs/a.pdf"},
    )
    assert up.status_code == 200
    listed = await client.get("/api/v1/production/jobs/tasks?so=SO/1H/API")
    assert listed.status_code == 200
    kinds2 = {t["kind"]: t["state"] for t in listed.json()["tasks"]}
    assert kinds2["design_upload"] == "done"
    assert kinds2["design_approve"] == "actionable"

    # Approve design + bypass payment → schedule actionable
    await client.post(
        f"/api/v1/production/jobs/design/versions/{up.json()['id']}/decision",
        json={"decision": "approved", "bypass": True, "reason": "test setup bypass"},
    )
    await client.post(
        f"/api/v1/production/jobs/{job_id}/payment/bypass",
        json={"reason": "owner test bypass"},
    )
    listed3 = await client.get("/api/v1/production/jobs/tasks?so=SO/1H/API")
    kinds3 = {t["kind"]: t["state"] for t in listed3.json()["tasks"]}
    assert kinds3["design_approve"] == "done"
    assert kinds3["schedule"] == "actionable"

    # Create assignment → screen/prepare actionable in parallel
    asg = await client.post(
        f"/api/v1/production/jobs/{job_id}/schedule/assignments",
        json={
            "so_line_id": "L1",
            "color_pass": 1,
            "operator_name": "Bima",
            "machine_name": "SA-01",
            "work_date": str(date.today()),
            "qty_planned": "100",
        },
    )
    assert asg.status_code == 200, asg.text
    listed4 = await client.get("/api/v1/production/jobs/tasks?so=SO/1H/API")
    kinds4 = {t["kind"]: t["state"] for t in listed4.json()["tasks"]}
    assert kinds4["schedule"] == "done"
    assert kinds4["screen"] == "actionable"
    assert kinds4["prepare"] == "actionable"
    assert "sample" not in kinds4


@pytest.mark.asyncio
async def test_tasks_api_non_print_no_screen(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/production/jobs",
        json={
            "accurate_so_number": "SO/1H/STOCK",
            "branch_id": "branch-a",
            "line_items": [
                {
                    "accurate_line_id": "NP1",
                    "quantity": "50",
                    "production_process": "non_print",
                }
            ],
        },
    )
    assert created.status_code == 200
    job_id = created.json()["id"]
    await client.post(
        f"/api/v1/production/jobs/{job_id}/payment/bypass",
        json={"reason": "nonprint payment bypass"},
    )
    listed = await client.get("/api/v1/production/jobs/tasks?so=SO/1H/STOCK")
    kinds = {t["kind"] for t in listed.json()["tasks"]}
    assert "stockpack" in kinds
    assert "stockprep" not in kinds
    assert "screen" not in kinds
    assert "print" not in kinds
    assert "design_upload" not in kinds
