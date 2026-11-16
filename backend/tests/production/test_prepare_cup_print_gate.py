"""Prepare Cup (= prep_helper): print-only, no UNKNOWN→print, per-line sample gate."""

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

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import dispose_engine, get_engine, get_session_factory
from app.main import create_app
from app.models.production.event import ProductionEvent
from app.models.production.prep import JobLineQty, PrepEvent, PrepState
from app.models.user import User
from app.services.production import permissions as P
from app.services.production.engine import derive_team_tasks_for_job

get_settings.cache_clear()

ALL_PERMS = [
    P.JOB_CREATE,
    P.JOB_READ,
    P.JOB_CANCEL,
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
                role="direktur",
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


async def _gates_and_job(client: AsyncClient, h: dict, so: str) -> int:
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
    return job_id


async def _seed_lines(job_id: int, rows: list[tuple[str, str, str]]) -> None:
    """rows: (so_line_id, po_qty, production_process)."""
    factory = get_session_factory()
    async with factory() as session:
        for lid, qty, proc in rows:
            session.add(
                JobLineQty(
                    job_id=job_id,
                    so_line_id=lid,
                    po_qty=Decimal(qty),
                    production_process=proc,
                )
            )
        await session.commit()


async def _schedule(
    client: AsyncClient, h: dict, job_id: int, line: str, qty: str = "50"
) -> int:
    asg = (
        await client.post(
            f"/api/v1/production/jobs/{job_id}/schedule/assignments",
            headers=h,
            json={
                "so_line_id": line,
                "color_pass": 1,
                "operator_name": "Rizki",
                "machine_name": "Semi Auto 01",
                "work_date": str(date.today()),
                "qty_planned": qty,
            },
        )
    ).json()
    return asg["id"]


@pytest.mark.asyncio
async def test_unknown_classification_rejects_prep_and_does_not_mutate(
    client: AsyncClient,
) -> None:
    h = await _auth(client)
    job_id = await _gates_and_job(client, h, "SO/CUP/UNK")
    await _seed_lines(job_id, [("line-u", "40", "unknown")])
    asg = await _schedule(client, h, job_id, "line-u", "40")

    blocked = await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/helper",
        headers=h,
        json={
            "so_line_id": "line-u",
            "qty": "10",
            "po_qty": "40",
            "evidence_ref": "cup-u",
            "idempotency_key": "cup-unknown-001",
            "assignment_id": asg,
        },
    )
    assert blocked.status_code == 409
    assert "UNKNOWN" in blocked.text

    factory = get_session_factory()
    async with factory() as session:
        row = await session.scalar(
            select(JobLineQty).where(
                JobLineQty.job_id == job_id, JobLineQty.so_line_id == "line-u"
            )
        )
        assert row is not None
        assert (row.production_process or "").lower() == "unknown"
        preps = list(
            (await session.scalars(select(PrepState).where(PrepState.job_id == job_id))).all()
        )
        assert preps == []


@pytest.mark.asyncio
async def test_prepare_cup_contract_and_non_print_blocked(client: AsyncClient) -> None:
    h = await _auth(client)
    job_id = await _gates_and_job(client, h, "SO/CUP/001")
    await _seed_lines(
        job_id,
        [("line-print", "50", "print"), ("line-stock", "10", "non_print")],
    )
    asg = await _schedule(client, h, job_id, "line-print")

    blocked = await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/helper",
        headers=h,
        json={
            "so_line_id": "line-stock",
            "qty": "5",
            "po_qty": "10",
            "evidence_ref": "cup-np",
            "idempotency_key": "cup-np-0001",
        },
    )
    assert blocked.status_code == 409

    cup = await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/helper",
        headers=h,
        json={
            "so_line_id": "line-print",
            "qty": "40",
            "po_qty": "50",
            "evidence_ref": "cup-1",
            "idempotency_key": "cup-ok-0001",
            "assignment_id": asg,
        },
    )
    assert cup.status_code == 200, cup.text
    body = cup.json()
    assert body["prep_kind"] == "prepare_cup"
    assert body["label"] == "Prepare Cup"

    # Idempotent retry same key
    again = await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/helper",
        headers=h,
        json={
            "so_line_id": "line-print",
            "qty": "40",
            "po_qty": "50",
            "evidence_ref": "cup-1",
            "idempotency_key": "cup-ok-0001",
            "assignment_id": asg,
        },
    )
    assert again.status_code == 409

    screen = await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/screener",
        headers=h,
        json={
            "so_line_id": "line-print",
            "qty": "1",
            "screen_size": "kecil",
            "evidence_ref": "scr-1",
            "idempotency_key": "scr-ok-0001",
            "assignment_id": asg,
        },
    )
    assert screen.status_code == 200
    assert screen.json()["prep_kind"] == "prepare_screen"


@pytest.mark.asyncio
async def test_sample_blocked_until_both_preps_per_print_line(
    client: AsyncClient,
) -> None:
    h = await _auth(client)
    job_id = await _gates_and_job(client, h, "SO/CUP/002")
    await _seed_lines(
        job_id,
        [("line-a", "30", "print"), ("line-b", "20", "print")],
    )
    a1 = await _schedule(client, h, job_id, "line-a", "30")
    a2 = await _schedule(client, h, job_id, "line-b", "20")

    r = await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/screener",
        headers=h,
        json={
            "so_line_id": "line-a",
            "qty": "1",
            "screen_size": "besar",
            "evidence_ref": "screen-a",
            "idempotency_key": "screen-line-a-001",
            "assignment_id": a1,
        },
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/helper",
        headers=h,
        json={
            "so_line_id": "line-a",
            "qty": "30",
            "po_qty": "30",
            "evidence_ref": "cup-a",
            "idempotency_key": "cup-line-a-001",
            "assignment_id": a1,
        },
    )
    assert r.status_code == 200, r.text

    blocked = await client.post(
        f"/api/v1/production/jobs/{job_id}/samples",
        headers=h,
        json={"file_name": "samp.pdf", "storage_key": "samp"},
    )
    assert blocked.status_code == 409
    assert "line-b" in blocked.text

    r = await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/helper",
        headers=h,
        json={
            "so_line_id": "line-b",
            "qty": "20",
            "po_qty": "20",
            "evidence_ref": "cup-b",
            "idempotency_key": "cup-line-b-001",
            "assignment_id": a2,
        },
    )
    assert r.status_code == 200, r.text
    still = await client.post(
        f"/api/v1/production/jobs/{job_id}/samples",
        headers=h,
        json={"file_name": "samp2.pdf", "storage_key": "samp2"},
    )
    assert still.status_code == 409

    r = await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/screener",
        headers=h,
        json={
            "so_line_id": "line-b",
            "qty": "1",
            "screen_size": "kecil",
            "evidence_ref": "screen-b",
            "idempotency_key": "screen-line-b-001",
            "assignment_id": a2,
        },
    )
    assert r.status_code == 200, r.text
    ok = await client.post(
        f"/api/v1/production/jobs/{job_id}/samples",
        headers=h,
        json={"file_name": "samp3.pdf", "storage_key": "samp3"},
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_concurrent_prepare_cup_same_line(client: AsyncClient) -> None:
    h = await _auth(client)
    job_id = await _gates_and_job(client, h, "SO/CUP/CONC")
    await _seed_lines(job_id, [("line-p", "50", "print")])
    asg = await _schedule(client, h, job_id, "line-p", "50")

    async def _post(key: str, qty: str):
        return await client.post(
            f"/api/v1/production/jobs/{job_id}/prep/helper",
            headers=h,
            json={
                "so_line_id": "line-p",
                "qty": qty,
                "po_qty": "50",
                "evidence_ref": f"cup-{key}",
                "idempotency_key": key,
                "assignment_id": asg,
            },
        )

    r1, r2 = await asyncio.gather(
        _post("cup-conc-aaa1", "30"),
        _post("cup-conc-bbb2", "40"),
    )
    codes = sorted([r1.status_code, r2.status_code])
    assert codes[0] == 200
    assert codes[1] in {200, 409}
    factory = get_session_factory()
    async with factory() as session:
        state = await session.scalar(
            select(PrepState).where(
                PrepState.job_id == job_id,
                PrepState.so_line_id == "line-p",
                PrepState.role == "helper",
            )
        )
        assert state is not None
        assert Decimal(state.qty) in {Decimal("30"), Decimal("40")}


@pytest.mark.asyncio
async def test_cancel_after_prep_preserves_audit_and_blocks_new_gate(
    client: AsyncClient,
) -> None:
    h = await _auth(client)
    job_id = await _gates_and_job(client, h, "SO/CUP/CANCEL")
    await _seed_lines(job_id, [("line-old", "50", "print")])
    asg = await _schedule(client, h, job_id, "line-old", "50")
    assert (
        await client.post(
            f"/api/v1/production/jobs/{job_id}/prep/screener",
            headers=h,
            json={
                "so_line_id": "line-old",
                "qty": "1",
                "screen_size": "kecil",
                "evidence_ref": "scr-old",
                "idempotency_key": "scr-old-0001",
                "assignment_id": asg,
            },
        )
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/production/jobs/{job_id}/prep/helper",
            headers=h,
            json={
                "so_line_id": "line-old",
                "qty": "50",
                "po_qty": "50",
                "evidence_ref": "cup-old",
                "idempotency_key": "cup-old-0001",
                "assignment_id": asg,
            },
        )
    ).status_code == 200

    cancel = await client.post(
        f"/api/v1/production/jobs/{job_id}/cancel",
        headers=h,
        json={
            "reason": "SO direvisi pelanggan",
            "idempotency_key": "cancel-job-0001",
            "confirm_review": True,
        },
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json().get("lifecycle_status") == "cancelled"

    # Histori prep tetap
    factory = get_session_factory()
    async with factory() as session:
        preps = list(
            (await session.scalars(select(PrepState).where(PrepState.job_id == job_id))).all()
        )
        events = list(
            (await session.scalars(select(PrepEvent).where(PrepEvent.job_id == job_id))).all()
        )
        assert len(preps) >= 2
        assert len(events) >= 2

    # Prep baru pada job cancelled ditolak
    blocked = await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/helper",
        headers=h,
        json={
            "so_line_id": "line-old",
            "qty": "10",
            "po_qty": "50",
            "evidence_ref": "cup-after-cancel",
            "idempotency_key": "cup-after-cancel-1",
            "assignment_id": asg,
        },
    )
    assert blocked.status_code in {409, 403, 422}

    # Job baru (revisi) line id berbeda — event lama tidak membuka gate
    job2 = await _gates_and_job(client, h, "SO/CUP/CANCEL-R2")
    await _seed_lines(job2, [("line-new", "50", "print")])
    asg2 = await _schedule(client, h, job2, "line-new", "50")
    sample_early = await client.post(
        f"/api/v1/production/jobs/{job2}/samples",
        headers=h,
        json={"file_name": "early.pdf", "storage_key": "early"},
    )
    assert sample_early.status_code == 409
    assert (
        await client.post(
            f"/api/v1/production/jobs/{job2}/prep/screener",
            headers=h,
            json={
                "so_line_id": "line-new",
                "qty": "1",
                "screen_size": "besar",
                "evidence_ref": "scr-new",
                "idempotency_key": "scr-new-0001",
                "assignment_id": asg2,
            },
        )
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/production/jobs/{job2}/prep/helper",
            headers=h,
            json={
                "so_line_id": "line-new",
                "qty": "50",
                "po_qty": "50",
                "evidence_ref": "cup-new",
                "idempotency_key": "cup-new-0001",
                "assignment_id": asg2,
            },
        )
    ).status_code == 200
    ok = await client.post(
        f"/api/v1/production/jobs/{job2}/samples",
        headers=h,
        json={"file_name": "ok.pdf", "storage_key": "ok"},
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_derive_tasks_unknown_blocks_prepare() -> None:
    class _J:
        id = 1
        accurate_so_number = "SO/X"
        branch_id = "branch-a"
        customer_name = "Cust"
        design_status = "approved"
        payment_status = "approved"
        sample_status = "not_required"
        processing_status = "Terproses"

    class _L:
        def __init__(self, lid, proc="print"):
            self.so_line_id = lid
            self.production_process = proc
            self.line_status = "active"
            self.po_qty = Decimal("10")

    class _A:
        def __init__(self, lid):
            self.so_line_id = lid
            self.status = "active"

    class _P:
        def __init__(self, lid, role, qty):
            self.so_line_id = lid
            self.role = role
            self.qty = Decimal(qty)

    job = _J()
    # Unknown scheduled → blocked, not actionable
    tasks_u = derive_team_tasks_for_job(
        job,
        lines=[_L("a", "unknown")],
        designs=[],
        assignments=[_A("a")],
        prep_states=[],
        samples=[],
        events=[],
        payment_status="approved",
    )
    # has_print false when only unknown — may not emit screen/prepare under print branch.
    # Seed mixed: one print ready sibling must not finish unknown sibling.
    tasks = derive_team_tasks_for_job(
        job,
        lines=[_L("a"), _L("b"), _L("stock", "non_print")],
        designs=[],
        assignments=[_A("a"), _A("b")],
        prep_states=[_P("a", "screener", "1"), _P("a", "helper", "10")],
        samples=[],
        events=[],
        payment_status="approved",
    )
    by = {t["group"]: t["state"] for t in tasks}
    assert by.get("screen") == "actionable"
    assert by.get("prepare") == "actionable"

    tasks2 = derive_team_tasks_for_job(
        job,
        lines=[_L("a"), _L("b"), _L("stock", "non_print")],
        designs=[],
        assignments=[_A("a"), _A("b")],
        prep_states=[
            _P("a", "screener", "1"),
            _P("a", "helper", "10"),
            _P("b", "screener", "1"),
            _P("b", "helper", "10"),
        ],
        samples=[],
        events=[],
        payment_status="approved",
    )
    by2 = {t["group"]: t["state"] for t in tasks2}
    assert by2.get("screen") == "done"
    assert by2.get("prepare") == "done"

    # Unknown on scheduled line blocks prep tasks even if print sibling ready
    tasks3 = derive_team_tasks_for_job(
        job,
        lines=[_L("a"), _L("u", "unknown")],
        designs=[],
        assignments=[_A("a"), _A("u")],
        prep_states=[_P("a", "screener", "1"), _P("a", "helper", "10")],
        samples=[],
        events=[],
        payment_status="approved",
    )
    by3 = {t["group"]: t["state"] for t in tasks3}
    assert by3.get("screen") == "blocked"
    assert by3.get("prepare") == "blocked"
    assert tasks_u is not None  # smoke: derivation does not crash on unknown-only
