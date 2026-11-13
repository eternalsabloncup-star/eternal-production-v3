"""Phase 3.1 hardening: evidence fail-closed, invalidate audit, idempotency."""

from __future__ import annotations

import asyncio
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
    P.PAYMENT_REVOKE,
    P.SCHEDULE_MANAGE,
    P.PREP_SCREENER,
    P.PREP_HELPER,
    P.SAMPLE_UPLOAD,
    P.SAMPLE_DECIDE,
    P.OUTPUT_CONFIRM,
    P.OUTPUT_HELPER_VERIFY,
    P.REJECT_RECORD,
    P.REJECT_VERIFY,
    P.PACKING_RECORD,
    P.DELIVERY_MANAGE,
    P.TRACKING_READ,
    P.PAYROLL_MANAGE,
    P.PAYROLL_READ,
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
        session.add(
            User(
                username="other.branch",
                display_name="Other",
                role="produksi",
                password_hash=hash_password("secret-pass"),
                permissions=ALL_PERMS,
                branch_ids=["branch-b"],
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


async def _login(client: AsyncClient, user="prod.lead") -> dict:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": user, "password": "secret-pass"},
    )
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _job(client, h, so="SO/H31/001"):
    job = (
        await client.post(
            "/api/v1/production/jobs",
            headers=h,
            json={"accurate_so_number": so, "branch_id": "branch-a"},
        )
    ).json()
    d = (
        await client.post(
            f"/api/v1/production/jobs/{job['id']}/design/versions",
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
        f"/api/v1/production/jobs/{job['id']}/payment/bypass",
        headers=h,
        json={"reason": "authorized bypass for hardening"},
    )
    return job["id"]


@pytest.mark.asyncio
async def test_evidence_capability_and_enforce_blocks_receipt(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = await _login(client)
    cap = await client.get(
        "/api/v1/production/jobs/evidence/capability", headers=h
    )
    assert cap.status_code == 200
    assert "receipt_verify" in cap.json()

    monkeypatch.setenv("V3_ACCURATE_EVIDENCE_ENFORCE", "true")
    get_settings.cache_clear()
    # Unconfigured gateway → fail closed
    monkeypatch.setenv("V3_ACCURATE_READ_GATEWAY_URL", "")
    monkeypatch.setenv("V3_ACCURATE_READ_GATEWAY_TOKEN", "")
    get_settings.cache_clear()

    job_id = await _job(client, h, "SO/H31/EVID")
    # Payment already bypassed in _job; recording another receipt should still
    # attempt evidence and fail closed when enforce is on.
    blocked = await client.post(
        f"/api/v1/production/jobs/{job_id}/payment/receipts",
        headers=h,
        json={"accurate_receipt_id": "RCV-X"},
    )
    assert blocked.status_code in {503, 409}
    monkeypatch.delenv("V3_ACCURATE_EVIDENCE_ENFORCE", raising=False)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_invalidate_receipt_audits_and_closes_gate(
    client: AsyncClient,
) -> None:
    h = await _login(client)
    job = (
        await client.post(
            "/api/v1/production/jobs",
            headers=h,
            json={"accurate_so_number": "SO/H31/INV", "branch_id": "branch-a"},
        )
    ).json()
    d = (
        await client.post(
            f"/api/v1/production/jobs/{job['id']}/design/versions",
            headers=h,
            json={"file_name": "a.pdf", "storage_key": "a"},
        )
    ).json()
    await client.post(
        f"/api/v1/production/jobs/design/versions/{d['id']}/decision",
        headers=h,
        json={"decision": "approved", "bypass": True, "reason": "test setup bypass"},
    )
    rec = (
        await client.post(
            f"/api/v1/production/jobs/{job['id']}/payment/receipts",
            headers=h,
            json={"accurate_receipt_id": "RCV-INV"},
        )
    ).json()
    inv = await client.post(
        f"/api/v1/production/jobs/payment/receipts/{rec['id']}/invalidate",
        headers=h,
        json={"reason": "reversed in Accurate"},
    )
    assert inv.status_code == 200
    state = await client.get(
        f"/api/v1/production/jobs/{job['id']}", headers=h
    )
    assert state.json()["payment_status"] == "pending"
    board = await client.get(
        f"/api/v1/production/jobs/{job['id']}/board", headers=h
    )
    types = [e["event_type"] for e in board.json()["events"]]
    assert "payment_receipt_invalidated" in types


@pytest.mark.asyncio
async def test_idempotent_output_concurrent(client: AsyncClient) -> None:
    h = await _login(client)
    job_id = await _job(client, h, "SO/H31/IDEM")
    asg = (
        await client.post(
            f"/api/v1/production/jobs/{job_id}/schedule/assignments",
            headers=h,
            json={
                "so_line_id": "line-1",
                "color_pass": 1,
                "operator_name": "Rizki",
                "machine_name": "M1",
                "work_date": str(date.today()),
                "qty_planned": "10",
            },
        )
    ).json()
    await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/screener",
        headers=h,
        json={
            "so_line_id": "line-1",
            "qty": "1",
            "screen_size": "kecil",
            "evidence_ref": "s",
            "idempotency_key": "scr-idem-1",
        },
    )
    await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/helper",
        headers=h,
        json={
            "so_line_id": "line-1",
            "qty": "10",
            "po_qty": "10",
            "evidence_ref": "h",
            "idempotency_key": "hlp-idem-1",
        },
    )

    async def once():
        return await client.post(
            f"/api/v1/production/jobs/{job_id}/outputs",
            headers=h,
            json={
                "assignment_id": asg["id"],
                "qty_physical": "5",
                "idempotency_key": "same-out-key",
            },
        )

    r1, r2 = await asyncio.gather(once(), once())
    codes = sorted([r1.status_code, r2.status_code])
    assert codes[0] == 200
    assert codes[1] == 409


@pytest.mark.asyncio
async def test_cross_po_branch_denial_and_expired_session(
    client: AsyncClient,
) -> None:
    h = await _login(client)
    job_id = await _job(client, h, "SO/H31/ISO")
    other = await _login(client, "other.branch")
    denied = await client.get(
        f"/api/v1/production/jobs/{job_id}", headers=other
    )
    assert denied.status_code == 403
    unauth = await client.get(f"/api/v1/production/jobs/{job_id}")
    assert unauth.status_code == 401
    bad = await client.get(
        f"/api/v1/production/jobs/{job_id}",
        headers={"Authorization": "Bearer dead.token.value"},
    )
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_payroll_excludes_daily_overtime(client: AsyncClient) -> None:
    h = await _login(client)
    job_id = await _job(client, h, "SO/H31/PAY")
    asg = (
        await client.post(
            f"/api/v1/production/jobs/{job_id}/schedule/assignments",
            headers=h,
            json={
                "so_line_id": "line-1",
                "color_pass": 1,
                "operator_name": "Rizki",
                "machine_name": "M1",
                "work_date": str(date.today()),
                "qty_planned": "10",
            },
        )
    ).json()
    await client.post(
        f"/api/v1/production/jobs/{job_id}/prep/helper",
        headers=h,
        json={
            "so_line_id": "line-1",
            "qty": "10",
            "po_qty": "10",
            "evidence_ref": "h",
            "idempotency_key": "pay-helper-1",
        },
    )
    out = await client.post(
        f"/api/v1/production/jobs/{job_id}/outputs",
        headers=h,
        json={
            "assignment_id": asg["id"],
            "qty_physical": "4",
            "idempotency_key": "pay-out-h31",
        },
    )
    assert out.status_code == 200, out.text
    await client.post(
        "/api/v1/production/payroll/rates",
        headers=h,
        json={
            "component": "one",
            "amount": "10",
            "effective_from": "2020-01-01",
        },
    )
    await client.post(
        "/api/v1/production/payroll/rates",
        headers=h,
        json={
            "component": "daily",
            "amount": "100000",
            "effective_from": "2020-01-01",
        },
    )
    run = (
        await client.post(
            "/api/v1/production/payroll/runs",
            headers=h,
            json={
                "period_start": str(date.today()),
                "period_end": str(date.today()),
                "idempotency_key": "payrun-h31",
                "branch_id": "branch-a",
            },
        )
    ).json()
    detail = await client.get(
        f"/api/v1/production/payroll/runs/{run['id']}", headers=h
    )
    body = detail.json()
    assert "daily" in body["excluded_unverified_components"]
    assert body["v1_parity"] == "unverified"
    assert Decimal(body["lines"][0]["amount_gross"]) == Decimal("40.00")
