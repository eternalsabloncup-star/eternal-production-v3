"""Fase 3 — payment approval settings SIMPAN→BACA→PERMISSION→AUDIT (isolated PG)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.models.production.payment_settings import (
    CRITICAL_PAYMENT_SETTINGS,
    PaymentApprovalSettings,
    PaymentApprovalSettingsAudit,
)
from app.models.production.job import ProductionJob
from app.models.user import User
from app.services.production import engine, permissions as P
from app.services.production import payment_settings as pay_settings
from app.services.production.payment_gate import monitor_financial_fields


@pytest.fixture
async def case():
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_session_factory()() as session:
        director = User(
            username="fase3-dir",
            display_name="Direktur Fase3",
            role="Direktur",
            password_hash="unused",
            branch_ids=["BR-JKT"],
            permissions=[P.JOB_READ, P.PAYMENT_BYPASS],
        )
        operator = User(
            username="fase3-op",
            display_name="Operator",
            role="operator",
            password_hash="unused",
            branch_ids=["BR-JKT"],
            permissions=[P.JOB_READ],
        )
        job = ProductionJob(
            accurate_so_number="SO-F3-001",
            accurate_id="801",
            branch_id="BR-JKT",
            customer_name="PT Fase Tiga",
            design_status="bypassed",
        )
        session.add_all([director, operator, job])
        await session.commit()
        return director.id, operator.id, job.id


@pytest.mark.asyncio
async def test_read_creates_default_and_critical_locked(case):
    did, _oid, _jid = case
    async with get_session_factory()() as session:
        user = await session.get(User, did)
        body = await pay_settings.read_payment_approval(session, user)
    assert body["version"] == 1
    assert body["can_manage"] is True
    for key in CRITICAL_PAYMENT_SETTINGS:
        assert body["payment_approval"][key] is True
    assert body["payment_approval"]["bypass_enabled"] is False
    assert "bypass_enabled" not in body["critical_locked"]


@pytest.mark.asyncio
async def test_update_save_read_audit_and_stale_version(case):
    did, oid, _jid = case
    async with get_session_factory()() as session:
        director = await session.get(User, did)
        first = await pay_settings.read_payment_approval(session, director)
        assert first["payment_approval"]["bypass_enabled"] is False
        updated = await pay_settings.update_payment_approval(
            session,
            director,
            version=first["version"],
            payment_approval={
                **first["payment_approval"],
                "bypass_enabled": True,
                "notify_director_on_bypass": True,
            },
            reason="Aktifkan bypass dengan notifikasi Direktur",
        )
    assert updated["version"] == first["version"] + 1
    assert updated["payment_approval"]["bypass_enabled"] is True
    assert updated["payment_approval"]["notify_director_on_bypass"] is True
    for key in CRITICAL_PAYMENT_SETTINGS:
        assert updated["payment_approval"][key] is True

    async with get_session_factory()() as session:
        director = await session.get(User, did)
        again = await pay_settings.read_payment_approval(session, director)
        assert again["payment_approval"]["bypass_enabled"] is True
        audit = await pay_settings.list_payment_approval_audit(session, director, limit=5)
        assert len(audit["items"]) >= 1
        assert audit["items"][0]["action"] == "payment_approval.settings.update"
        assert await session.scalar(select(func.count()).select_from(PaymentApprovalSettingsAudit)) >= 1

        with pytest.raises(HTTPException) as stale:
            await pay_settings.update_payment_approval(
                session,
                director,
                version=first["version"],
                payment_approval=again["payment_approval"],
                reason="versi lama",
            )
        assert stale.value.status_code == 409

        operator = await session.get(User, oid)
        with pytest.raises(HTTPException) as denied:
            await pay_settings.update_payment_approval(
                session,
                operator,
                version=again["version"],
                payment_approval=again["payment_approval"],
                reason="coba tanpa izin",
            )
        assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_reject_weakening_critical_keys(case):
    did, _oid, _jid = case
    async with get_session_factory()() as session:
        director = await session.get(User, did)
        body = await pay_settings.read_payment_approval(session, director)
        with pytest.raises(HTTPException) as exc:
            await pay_settings.update_payment_approval(
                session,
                director,
                version=body["version"],
                payment_approval={**body["payment_approval"], "bypass_reason_required": False},
                reason="coba lemahkan kritis",
            )
        assert exc.value.status_code == 422


@pytest.mark.asyncio
@pytest.mark.respect_payment_bypass_setting
async def test_bypass_respects_settings_flag(case):
    did, _oid, jid = case
    async with get_session_factory()() as session:
        director = await session.get(User, did)
        body = await pay_settings.read_payment_approval(session, director)
        assert body["payment_approval"]["bypass_enabled"] is False
        job = await session.get(ProductionJob, jid)
        with pytest.raises(HTTPException) as exc:
            await engine.bypass_payment(session, director, job, reason="seharusnya ditolak settings")
        assert exc.value.status_code == 403
        assert "dinonaktifkan" in str(exc.value.detail).lower() or "Pengaturan" in str(exc.value.detail)
        # Enable then bypass succeeds; disable again blocks.
        enabled = await pay_settings.update_payment_approval(
            session,
            director,
            version=body["version"],
            payment_approval={**body["payment_approval"], "bypass_enabled": True},
            reason="aktifkan bypass untuk jalur sukses",
        )
        ok = await engine.bypass_payment(
            session, director, job, reason="bypass setelah enable settings", idempotency_key="f3-bypass-ok"
        )
        assert ok.active is True
        await pay_settings.update_payment_approval(
            session,
            director,
            version=enabled["version"],
            payment_approval={**enabled["payment_approval"], "bypass_enabled": False},
            reason="nonaktifkan lagi setelah tes",
        )


def test_monitor_financial_never_invents_lunas():
    fields = monitor_financial_fields(verified_amount="100.00", payment_status="approved")
    assert fields["financial_payment_status"] == "UNKNOWN"
    assert fields["financial_settlement_known"] is False
    assert fields["invoice_total"] is None
    assert fields["approval_source"] == "Penerimaan"
    assert fields["approved"] is True
    pending = monitor_financial_fields(verified_amount=None, payment_status="pending")
    assert pending["approval_source"] == "Belum Approved"
    assert pending["financial_payment_status"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_settings_branches_readonly_honest(case):
    """Cabang efektif read-only — tidak mengaku writable master sandbox."""
    from httpx import ASGITransport, AsyncClient

    from app.core.security import create_access_token
    from app.main import create_app

    did, _oid, _jid = case
    async with get_session_factory()() as session:
        director = await session.get(User, did)
        token = create_access_token(director)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(
            "/api/v1/production/settings/branches",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["can_manage"] is False
        assert body["persistence"] is None
        assert any(i["code"] == "BR-JKT" for i in body["items"])
        assert all(i.get("writable") is False for i in body["items"])
        machines = await ac.get(
            "/api/v1/production/settings/machines-summary",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert machines.status_code == 200
        mbody = machines.json()
        assert mbody["persistence"] == "production_machines"
        assert mbody["can_manage"] is True
