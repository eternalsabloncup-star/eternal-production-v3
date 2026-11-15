"""Fase 1C: soft-cancel lifecycle, re-input guards, revision markers — isolated test DB."""

from __future__ import annotations

import asyncio
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
from app.models.production.job import LIFECYCLE_CANCELLED, ProductionJob
from app.models.production.prep import (
    LINE_STATUS_CONFLICT,
    LINE_STATUS_REMOVED,
    JobLineQty,
)
from app.models.production.schedule import ScheduleAssignment
from app.models.user import User
from app.services.production import permissions as P

get_settings.cache_clear()

PERMS = [P.JOB_READ, P.JOB_CREATE, P.JOB_CANCEL, P.SCHEDULE_MANAGE]


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
                username="life.lead",
                display_name="Lifecycle Lead",
                role="kepala_produksi",
                password_hash=hash_password("secret-pass"),
                permissions=PERMS,
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="life.noperm",
                display_name="No Cancel",
                role="operator",
                password_hash=hash_password("secret-pass"),
                permissions=[P.JOB_READ, P.JOB_CREATE],
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="life.other",
                display_name="Other Branch",
                role="operator",
                password_hash=hash_password("secret-pass"),
                permissions=PERMS,
                branch_ids=["branch-b"],
                is_active=True,
            )
        )
        await session.commit()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login = await ac.post(
            "/api/v1/auth/login",
            json={"username": "life.lead", "password": "secret-pass"},
        )
        assert login.status_code == 200, login.text
        ac.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        yield ac
    await dispose_engine()
    get_settings.cache_clear()


async def _login(ac: AsyncClient, username: str) -> None:
    login = await ac.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "secret-pass"},
    )
    assert login.status_code == 200, login.text
    ac.headers["Authorization"] = f"Bearer {login.json()['access_token']}"


async def _create_job(client: AsyncClient, so: str, lines: list[dict] | None = None) -> int:
    body = {
        "accurate_so_number": so,
        "branch_id": "branch-a",
        "customer_name": "Cust",
        "line_items": lines
        if lines is not None
        else [
            {
                "id": "L1",
                "quantity": 100,
                "production_process": "print",
                "accurate_item_id": "IT1",
            }
        ],
    }
    r = await client.post("/api/v1/production/jobs", json=body)
    assert r.status_code == 200, r.text
    return int(r.json()["id"])


@pytest.mark.asyncio
async def test_cancel_job_without_activity(client):
    jid = await _create_job(client, "SO-LIFE-SAFE")
    gate = await client.get(f"/api/v1/production/jobs/{jid}/cancel-gate")
    assert gate.status_code == 200
    assert gate.json()["decision"] == "safe_auto"
    cancel = await client.post(
        f"/api/v1/production/jobs/{jid}/cancel",
        json={"reason": "batal pesanan customer", "idempotency_key": "cancel-safe-01"},
    )
    assert cancel.status_code == 200, cancel.text
    body = cancel.json()
    assert body["lifecycle_status"] == "cancelled"
    assert body["replay"] is False
    assert body["event_id"]
    detail = await client.get(f"/api/v1/production/jobs/{jid}")
    assert detail.json()["lifecycle_status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_repeat_idempotent(client):
    jid = await _create_job(client, "SO-LIFE-IDEM")
    a = await client.post(
        f"/api/v1/production/jobs/{jid}/cancel",
        json={"reason": "batal pertama", "idempotency_key": "cancel-idem-01"},
    )
    assert a.status_code == 200
    b = await client.post(
        f"/api/v1/production/jobs/{jid}/cancel",
        json={"reason": "batal pertama", "idempotency_key": "cancel-idem-01"},
    )
    assert b.status_code == 200
    assert b.json()["replay"] is True
    assert b.json()["event_id"] == a.json()["event_id"]
    c = await client.post(
        f"/api/v1/production/jobs/{jid}/cancel",
        json={"reason": "batal ulang lain", "idempotency_key": "cancel-idem-02"},
    )
    assert c.status_code == 200
    assert c.json()["replay"] is True
    assert c.json()["lifecycle_status"] == "cancelled"


@pytest.mark.asyncio
async def test_unauthorized_cancel(client):
    jid = await _create_job(client, "SO-LIFE-PERM")
    await _login(client, "life.noperm")
    r = await client.post(
        f"/api/v1/production/jobs/{jid}/cancel",
        json={"reason": "tanpa izin cancel", "idempotency_key": "cancel-noperm-01"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_branch_permission_cancel(client):
    jid = await _create_job(client, "SO-LIFE-BR")
    await _login(client, "life.other")
    r = await client.post(
        f"/api/v1/production/jobs/{jid}/cancel",
        json={"reason": "cabang salah cancel", "idempotency_key": "cancel-br-01"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_concurrent_cancel_requests(client):
    jid = await _create_job(client, "SO-LIFE-CONC")

    async def once(key: str):
        return await client.post(
            f"/api/v1/production/jobs/{jid}/cancel",
            json={"reason": "concurrent cancel ok", "idempotency_key": key},
        )

    r1, r2 = await asyncio.gather(once("cancel-conc-a"), once("cancel-conc-b"))
    assert r1.status_code == 200 and r2.status_code == 200
    bodies = [r1.json(), r2.json()]
    assert all(b["lifecycle_status"] == "cancelled" for b in bodies)
    assert sum(1 for b in bodies if not b["replay"]) == 1
    factory = get_session_factory()
    async with factory() as session:
        evs = (
            await session.scalars(
                select(ProductionEvent).where(
                    ProductionEvent.job_id == jid,
                    ProductionEvent.event_type == "job_cancelled",
                )
            )
        ).all()
        assert len(evs) == 1


@pytest.mark.asyncio
async def test_cancel_then_reinput_creates_new_active_job(client):
    so = "SO-LIFE-REIN"
    jid = await _create_job(
        client,
        so,
        lines=[{"id": "L1", "quantity": 100, "production_process": "print"}],
    )
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            ScheduleAssignment(
                job_id=jid,
                so_line_id="L1",
                color_pass=1,
                operator_name="Old Op",
                machine_name="Old M",
                work_date=date(2026, 11, 15),
                branch_id="branch-a",
                qty_planned=Decimal("10"),
                created_by=1,
            )
        )
        session.add(
            ProductionEvent(
                job_id=jid,
                event_type="note",
                so_line_id="L1",
                idempotency_key="note-old-01",
                actor_user_id=1,
                reason="histori lama",
            )
        )
        await session.commit()
    cancel = await client.post(
        f"/api/v1/production/jobs/{jid}/cancel",
        json={
            "reason": "cancel sebelum reinput",
            "idempotency_key": "cancel-rein-01",
            "confirm_review": True,
        },
    )
    assert cancel.status_code == 200, cancel.text
    again = await client.post(
        "/api/v1/production/jobs",
        json={
            "accurate_so_number": so,
            "branch_id": "branch-a",
            "line_items": [
                {"id": "L9", "quantity": 40, "production_process": "print"},
            ],
        },
    )
    assert again.status_code == 200, again.text
    new_id = again.json()["id"]
    assert new_id != jid
    assert again.json()["lifecycle_status"] == "active"
    # Active lookup resolves new job only.
    by_so = await client.get(f"/api/v1/production/jobs/by-so/{so}")
    assert by_so.status_code == 200
    assert by_so.json()["id"] == new_id
    # Old history preserved on cancelled job id; not inherited.
    async with factory() as session:
        old = await session.get(ProductionJob, jid)
        assert old.lifecycle_status == LIFECYCLE_CANCELLED
        old_asg = (
            await session.scalars(
                select(ScheduleAssignment).where(ScheduleAssignment.job_id == jid)
            )
        ).all()
        assert len(old_asg) == 1
        new_asg = (
            await session.scalars(
                select(ScheduleAssignment).where(ScheduleAssignment.job_id == new_id)
            )
        ).all()
        assert new_asg == []
        new_lines = (
            await session.scalars(select(JobLineQty).where(JobLineQty.job_id == new_id))
        ).all()
        assert {ln.so_line_id for ln in new_lines} == {"L9"}
        actives = (
            await session.scalars(
                select(ProductionJob).where(
                    ProductionJob.accurate_so_number == so,
                    ProductionJob.lifecycle_status == "active",
                )
            )
        ).all()
        assert len(actives) == 1 and actives[0].id == new_id


@pytest.mark.asyncio
async def test_multiple_cancelled_plus_one_active(client):
    so = "SO-LIFE-MULTI"
    ids = []
    for i in range(2):
        jid = await _create_job(client, so, lines=[{"id": f"L{i}", "quantity": 5, "production_process": "print"}])
        ids.append(jid)
        r = await client.post(
            f"/api/v1/production/jobs/{jid}/cancel",
            json={"reason": f"cancel versi {i}", "idempotency_key": f"cancel-multi-{i}"},
        )
        assert r.status_code == 200, r.text
    active = await _create_job(
        client, so, lines=[{"id": "L-ACTIVE", "quantity": 7, "production_process": "print"}]
    )
    assert active not in ids
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.scalars(
                select(ProductionJob).where(ProductionJob.accurate_so_number == so)
            )
        ).all()
        assert len(rows) == 3
        assert sum(1 for r in rows if r.lifecycle_status == "active") == 1
        assert sum(1 for r in rows if r.lifecycle_status == "cancelled") == 2


@pytest.mark.asyncio
async def test_concurrent_reinput_single_active(client):
    so = "SO-LIFE-CONC-RE"
    jid = await _create_job(client, so)
    await client.post(
        f"/api/v1/production/jobs/{jid}/cancel",
        json={"reason": "siap reinput concurrent", "idempotency_key": "cancel-concre-01"},
    )

    async def once(key: str):
        return await client.post(
            "/api/v1/production/jobs",
            json={
                "accurate_so_number": so,
                "branch_id": "branch-a",
                "line_items": [{"id": "LN", "quantity": 3, "production_process": "print"}],
                "customer_name": key,
            },
        )

    r1, r2 = await asyncio.gather(once("a"), once("b"))
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
    factory = get_session_factory()
    async with factory() as session:
        actives = (
            await session.scalars(
                select(ProductionJob).where(
                    ProductionJob.accurate_so_number == so,
                    ProductionJob.lifecycle_status == "active",
                )
            )
        ).all()
        assert len(actives) == 1


@pytest.mark.asyncio
async def test_director_role_can_cancel_without_explicit_perm(client):
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            User(
                username="life.dir",
                display_name="Direktur",
                role="Direktur",
                password_hash=hash_password("secret-pass"),
                permissions=[P.JOB_READ, P.JOB_CREATE],  # no JOB_CANCEL
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        await session.commit()
    await _login(client, "life.lead")
    jid = await _create_job(client, "SO-LIFE-DIR")
    await _login(client, "life.dir")
    r = await client.post(
        f"/api/v1/production/jobs/{jid}/cancel",
        json={"reason": "direktur default cancel", "idempotency_key": "cancel-dir-01"},
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_identical_retry_import_no_duplicate(client):
    so = "SO-LIFE-RETRY"
    lines = [
        {"id": "L1", "quantity": 50, "production_process": "print", "accurate_item_id": "IT1"}
    ]
    a = await client.post(
        "/api/v1/production/jobs",
        json={"accurate_so_number": so, "branch_id": "branch-a", "line_items": lines},
    )
    b = await client.post(
        "/api/v1/production/jobs",
        json={"accurate_so_number": so, "branch_id": "branch-a", "line_items": lines},
    )
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["id"] == b.json()["id"]
    factory = get_session_factory()
    async with factory() as session:
        jobs = (
            await session.scalars(
                select(ProductionJob).where(ProductionJob.accurate_so_number == so)
            )
        ).all()
        assert len(jobs) == 1
        lines_db = (
            await session.scalars(select(JobLineQty).where(JobLineQty.job_id == jobs[0].id))
        ).all()
        assert len(lines_db) == 1


@pytest.mark.asyncio
async def test_revision_item_qty_and_removed_line(client):
    so = "SO-LIFE-REV"
    jid = await _create_job(
        client,
        so,
        lines=[
            {"id": "L1", "quantity": 100, "production_process": "print"},
            {"id": "L2", "quantity": 20, "production_process": "print"},
        ],
    )
    # New item + qty change on idle line + remove L2
    r = await client.post(
        "/api/v1/production/jobs",
        json={
            "accurate_so_number": so,
            "branch_id": "branch-a",
            "line_items": [
                {"id": "L1", "quantity": 80, "production_process": "print"},
                {"id": "L3", "quantity": 10, "production_process": "print"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    factory = get_session_factory()
    async with factory() as session:
        rows = {
            x.so_line_id: x
            for x in (
                await session.scalars(select(JobLineQty).where(JobLineQty.job_id == jid))
            ).all()
        }
        assert rows["L1"].po_qty == Decimal("80")
        assert rows["L1"].line_status == "active"
        assert rows["L2"].line_status == LINE_STATUS_REMOVED
        assert rows["L3"].po_qty == Decimal("10")


@pytest.mark.asyncio
async def test_qty_revised_below_completed_marks_conflict(client):
    jid = await _create_job(client, "SO-LIFE-QTY")
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            ProductionEvent(
                job_id=jid,
                event_type="output_confirmed",
                so_line_id="L1",
                color_pass=1,
                qty_physical=Decimal("40"),
                idempotency_key="out-life-01",
                actor_user_id=1,
            )
        )
        await session.commit()
    r = await client.post(
        "/api/v1/production/jobs",
        json={
            "accurate_so_number": "SO-LIFE-QTY",
            "branch_id": "branch-a",
            "line_items": [{"id": "L1", "quantity": 10, "production_process": "print"}],
        },
    )
    assert r.status_code == 200
    async with factory() as session:
        line = await session.scalar(
            select(JobLineQty).where(JobLineQty.job_id == jid, JobLineQty.so_line_id == "L1")
        )
        assert line.po_qty == Decimal("100")  # never silently rewritten
        assert line.source_qty == Decimal("10")
        assert line.line_status == LINE_STATUS_CONFLICT


@pytest.mark.asyncio
async def test_cancel_with_assignment_requires_review(client):
    jid = await _create_job(client, "SO-LIFE-ASG")
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            ScheduleAssignment(
                job_id=jid,
                so_line_id="L1",
                color_pass=1,
                operator_name="Op A",
                machine_name="M1",
                work_date=date(2026, 11, 15),
                branch_id="branch-a",
                qty_planned=Decimal("10"),
                created_by=1,
            )
        )
        await session.commit()
    gate = await client.get(f"/api/v1/production/jobs/{jid}/cancel-gate")
    assert gate.json()["decision"] == "requires_review"
    blocked = await client.post(
        f"/api/v1/production/jobs/{jid}/cancel",
        json={"reason": "cancel dengan assignment", "idempotency_key": "cancel-asg-01"},
    )
    assert blocked.status_code == 409
    ok = await client.post(
        f"/api/v1/production/jobs/{jid}/cancel",
        json={
            "reason": "cancel dengan assignment",
            "idempotency_key": "cancel-asg-02",
            "confirm_review": True,
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["cancel_gate"] == "requires_review"


@pytest.mark.asyncio
async def test_cancel_with_physical_progress_blocked(client):
    jid = await _create_job(client, "SO-LIFE-PHYS")
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            ProductionEvent(
                job_id=jid,
                event_type="output_confirmed",
                so_line_id="L1",
                color_pass=1,
                qty_physical=Decimal("5"),
                idempotency_key="out-phys-01",
                actor_user_id=1,
            )
        )
        await session.commit()
    gate = await client.get(f"/api/v1/production/jobs/{jid}/cancel-gate")
    assert gate.json()["decision"] == "blocked"
    r = await client.post(
        f"/api/v1/production/jobs/{jid}/cancel",
        json={
            "reason": "cancel dengan progress",
            "idempotency_key": "cancel-phys-01",
            "confirm_review": True,
        },
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_cancel_with_sj_pod_blocked(client):
    jid = await _create_job(client, "SO-LIFE-SJ")
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            ProductionEvent(
                job_id=jid,
                event_type="pod",
                accurate_sj_id="SJ1",
                qty_physical=Decimal("1"),
                idempotency_key="pod-life-01",
                actor_user_id=1,
            )
        )
        await session.commit()
    assert (await client.get(f"/api/v1/production/jobs/{jid}/cancel-gate")).json()[
        "decision"
    ] == "blocked"


@pytest.mark.asyncio
async def test_cancel_with_payment_receipt_requires_review(client):
    jid = await _create_job(client, "SO-LIFE-PAY")
    factory = get_session_factory()
    async with factory() as session:
        from app.models.production.payment import PaymentReceiptRef

        session.add(
            PaymentReceiptRef(
                job_id=jid,
                accurate_receipt_id="R-LIFE-1",
                idempotency_key="pay-life-01",
                amount=Decimal("1000"),
                status="valid",
                recorded_by=1,
            )
        )
        await session.commit()
    gate = await client.get(f"/api/v1/production/jobs/{jid}/cancel-gate")
    assert gate.json()["decision"] == "requires_review"


@pytest.mark.asyncio
async def test_schedule_hides_cancelled_and_supports_flag(client):
    jid = await _create_job(client, "SO-LIFE-SCHED")
    await client.post(
        f"/api/v1/production/jobs/{jid}/cancel",
        json={"reason": "hide from schedule", "idempotency_key": "cancel-sched-01"},
    )
    sched = await client.get("/api/v1/production/ops/schedule")
    assert sched.status_code == 200
    data = sched.json()
    assert data["cancelled_jobs_supported"] is True
    assert all(i.get("job_id") != jid for i in data["items"])


@pytest.mark.asyncio
async def test_audit_trail_job_cancelled_event(client):
    jid = await _create_job(client, "SO-LIFE-AUD")
    await client.post(
        f"/api/v1/production/jobs/{jid}/cancel",
        json={"reason": "audit trail wajib ada", "idempotency_key": "cancel-aud-01"},
    )
    factory = get_session_factory()
    async with factory() as session:
        ev = await session.scalar(
            select(ProductionEvent).where(
                ProductionEvent.job_id == jid,
                ProductionEvent.event_type == "job_cancelled",
            )
        )
        assert ev is not None
        assert ev.actor_user_id is not None
        assert "batal" in (ev.reason or "").lower() or "audit" in (ev.reason or "").lower()
        job = await session.get(ProductionJob, jid)
        assert job.cancelled_by_user_id == ev.actor_user_id
        assert job.cancel_gate == "safe_auto"


@pytest.mark.asyncio
async def test_removed_line_with_assignment_is_conflict(client):
    jid = await _create_job(
        client,
        "SO-LIFE-RMASG",
        lines=[
            {"id": "L1", "quantity": 10, "production_process": "print"},
            {"id": "L2", "quantity": 10, "production_process": "print"},
        ],
    )
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            ScheduleAssignment(
                job_id=jid,
                so_line_id="L2",
                color_pass=1,
                operator_name="Op",
                machine_name="M",
                work_date=date(2026, 11, 15),
                branch_id="branch-a",
                qty_planned=Decimal("5"),
                created_by=1,
            )
        )
        await session.commit()
    r = await client.post(
        "/api/v1/production/jobs",
        json={
            "accurate_so_number": "SO-LIFE-RMASG",
            "branch_id": "branch-a",
            "line_items": [{"id": "L1", "quantity": 10, "production_process": "print"}],
        },
    )
    assert r.status_code == 200
    async with factory() as session:
        l2 = await session.scalar(
            select(JobLineQty).where(JobLineQty.job_id == jid, JobLineQty.so_line_id == "L2")
        )
        assert l2.line_status == LINE_STATUS_CONFLICT
