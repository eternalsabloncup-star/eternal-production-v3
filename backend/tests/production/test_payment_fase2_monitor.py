"""Fase 2 payment monitor / gate / bypass hardening — isolated PostgreSQL only."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.models.production.event import ProductionEvent
from app.models.production.job import ProductionJob
from app.models.production.payment import PaymentBypass, PaymentReceiptRef
from app.models.user import User
from app.services import accurate_evidence
from app.services.production import engine, permissions as P
from app.services.production.payment_gate import monitor_financial_fields


@pytest.fixture
async def case(monkeypatch):
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_session_factory()() as session:
        user = User(
            username="fase2-pay",
            display_name="Fase2",
            role="operator",
            password_hash="unused",
            branch_ids=["BR-JKT"],
            permissions=[P.PAYMENT_RECORD, P.PAYMENT_BYPASS, P.PAYMENT_REVOKE, P.JOB_READ],
        )
        job = ProductionJob(
            accurate_so_number="SO-F2-001",
            accurate_id="800",
            branch_id="BR-JKT",
            customer_name="PT Fase Dua",
            design_status="bypassed",
        )
        session.add_all([user, job])
        await session.commit()
        uid, jid = user.id, job.id

    payload = dict(
        id="910",
        number="RCP-910",
        sales_order_number="SO-F2-001",
        sales_order_id="800",
        branch={"id": "BR-JKT"},
        amount="500.00",
        paid_at="2026-11-10T08:00:00+07:00",
        status="POSTED",
        cancelled=False,
        reversed=False,
        verifiable=True,
        source="fixture",
        live_verified=False,
    )

    class Gateway:
        async def get(self, path, **kwargs):
            return dict(payload)

    monkeypatch.setattr(accurate_evidence, "ReadGateway", Gateway)
    return uid, jid, payload


async def ctx(case, session):
    return await session.get(User, case[0]), await session.get(ProductionJob, case[1])


async def enable_bypass_setting(session, user):
    """Seed bypass_enabled=true on disposable test DB (new installs default false).

    Uses ORM write on the settings row — mirrors Owner enabling via Settings API.
    """
    del user  # actor not required for test seed
    from app.models.production.payment_settings import DEFAULT_PAYMENT_SETTINGS
    from app.services.production import payment_settings as pay_settings

    row = await pay_settings.get_or_create_settings(session)
    cfg = dict(DEFAULT_PAYMENT_SETTINGS)
    if isinstance(row.config_json, dict):
        cfg.update({k: v for k, v in row.config_json.items() if isinstance(v, bool)})
    if cfg.get("bypass_enabled") is True:
        await session.commit()
        return
    cfg["bypass_enabled"] = True
    row.config_json = cfg
    await session.commit()


async def record(case, rid="910", **kwargs):
    async with get_session_factory()() as session:
        user, job = await ctx(case, session)
        row = await engine.record_payment_receipt(
            session, user, job, accurate_receipt_id=rid, **kwargs
        )
        return row.id, row.amount, job.payment_status, row.paid_at, job.payment_review_required


def test_monitor_financial_fields_never_invent_outstanding():
    fields = monitor_financial_fields(verified_amount="100.00", payment_status="approved")
    assert fields["production_approval_status"] == "approved"
    assert fields["financial_receipt_state"] == "verified_received"
    assert fields["invoice_amount"] is None
    assert fields["outstanding_amount"] is None
    assert fields["financial_settlement_known"] is False
    assert fields["financial_payment_status"] == "UNKNOWN"
    assert fields["approval_source"] == "Penerimaan"
    assert fields["invoice_total"] is None


async def test_no_verified_payment_stays_pending(case):
    async with get_session_factory()() as session:
        user, job = await ctx(case, session)
        assert job.payment_status == "pending"
        body = await engine.list_payment_receipts(session, user, q="SO-F2-001")
        row = body["items"][0]
        assert row["payment_status"] == "pending"
        assert row["verified_amount"] is None
        assert row["financial_receipt_state"] == "none"
        assert row["invoice_amount"] is None


async def test_partial_verified_receipt_opens_gate_and_stores_paid_at(case):
    rid, amount, status, paid_at, review = await record(case)
    assert amount == Decimal("500.00") and status == "approved" and review is False
    assert paid_at is not None and paid_at.year == 2026
    async with get_session_factory()() as session:
        user, _ = await ctx(case, session)
        body = await engine.list_payment_receipts(session, user, q="SO-F2-001")
        item = body["items"][0]
        assert item["payment_status"] == "approved"
        assert item["production_approval_status"] == "approved"
        assert item["verified_amount"] == "500.00"
        assert item["payment_date"] is not None
        assert item["outstanding_amount"] is None
        assert item["receipts"][0]["paid_at"] is not None


async def test_multiple_receipts_sum_verified_amount(case):
    await record(case, rid="910", idempotency_key="f2-receipt-1")
    case[2].update(id="911", number="RCP-911", amount="250.00")
    await record(case, rid="911", idempotency_key="f2-receipt-2")
    async with get_session_factory()() as session:
        user, _ = await ctx(case, session)
        item = (await engine.list_payment_receipts(session, user, q="SO-F2-001"))["items"][0]
        assert item["verified_amount"] == "750.00"
        assert item["receipt_count"] == 2
        assert item["payment_status"] == "approved"


async def test_invalidate_one_of_two_keeps_gate(case):
    first, *_ = await record(case, rid="910", idempotency_key="f2-keep-1")
    case[2].update(id="911", number="RCP-911", amount="100.00")
    await record(case, rid="911", idempotency_key="f2-keep-2")
    async with get_session_factory()() as session:
        user, job = await ctx(case, session)
        await engine.invalidate_receipt(session, user, first, reason="receipt cancelled upstream")
        assert job.payment_status == "approved"
        assert job.payment_review_required is False


async def test_gateway_unavailable_fail_closed(case, monkeypatch):
    class Down:
        async def get(self, path, **kwargs):
            raise HTTPException(503, "offline")

    monkeypatch.setattr(accurate_evidence, "ReadGateway", Down)
    with pytest.raises(HTTPException) as exc:
        await record(case)
    assert exc.value.status_code == 503
    async with get_session_factory()() as session:
        job = await session.get(ProductionJob, case[1])
        assert job.payment_status == "pending"
        assert await session.scalar(select(func.count()).select_from(PaymentReceiptRef)) == 0


async def test_wrong_so_association_rejected(case):
    case[2]["sales_order_number"] = "SO-OTHER"
    with pytest.raises(HTTPException) as exc:
        await record(case)
    assert exc.value.status_code == 409


async def test_cross_branch_unauthorized(case):
    async with get_session_factory()() as session:
        user, job = await ctx(case, session)
        await enable_bypass_setting(session, user)
        user.branch_ids = ["BR-OTHER"]
        with pytest.raises(HTTPException) as exc:
            await engine.bypass_payment(session, user, job, reason="wrong branch attempt")
        assert exc.value.status_code == 403


async def test_authorized_bypass_reason_and_audit(case):
    async with get_session_factory()() as session:
        user, job = await ctx(case, session)
        await enable_bypass_setting(session, user)
        row = await engine.bypass_payment(
            session, user, job, reason="Director tempo approval", idempotency_key="bypass-f2-1"
        )
        assert row.active and row.gate_before == "pending"
        assert job.payment_status == "bypassed"
        assert await session.scalar(
            select(func.count()).select_from(ProductionEvent).where(
                ProductionEvent.event_type == "payment_bypass_authorized"
            )
        ) == 1


async def test_unauthorized_bypass_and_missing_reason(case):
    async with get_session_factory()() as session:
        user, job = await ctx(case, session)
        await enable_bypass_setting(session, user)
        user.permissions = []
        user.role = "operator"
        with pytest.raises(HTTPException) as exc:
            await engine.bypass_payment(session, user, job, reason="no grant")
        assert exc.value.status_code == 403
        await session.rollback()
    async with get_session_factory()() as session:
        user, job = await ctx(case, session)
        await enable_bypass_setting(session, user)
        with pytest.raises(HTTPException) as exc:
            await engine.bypass_payment(session, user, job, reason="  ")
        assert exc.value.status_code == 422


async def test_direktur_legacy_default_allows_without_jsonb_permission(case):
    async with get_session_factory()() as session:
        user, job = await ctx(case, session)
        user.permissions = []  # no production.payment.bypass JSONB
        user.role = "Direktur"
        await enable_bypass_setting(session, user)
        row = await engine.bypass_payment(
            session, user, job, reason="Direktur tempo approval", idempotency_key="bypass-dir-legacy-1"
        )
        assert row.active is True
        assert job.payment_status == "bypassed"


async def test_direktur_with_explicit_permission_still_allowed(case):
    async with get_session_factory()() as session:
        user, job = await ctx(case, session)
        user.role = "Direktur"
        user.permissions = [P.PAYMENT_BYPASS]
        await enable_bypass_setting(session, user)
        row = await engine.bypass_payment(
            session, user, job, reason="explicit grant path", idempotency_key="bypass-dir-explicit-1"
        )
        assert row.active is True


async def test_role_spoof_via_request_fields_is_ignored(case):
    """Client cannot elevate by inventing role strings on the request body — only User.role."""
    assert P.user_may_bypass_payment(
        type("U", (), {"role": "Direktur", "permissions": [], "_workflow_context": None})()
    )
    assert not P.user_may_bypass_payment(
        type("U", (), {"role": "operator", "permissions": [], "_workflow_context": None})()
    )
    # Spoofed "Direktur" in an unrelated attribute must not grant access.
    assert not P.user_may_bypass_payment(
        type(
            "U",
            (),
            {
                "role": "operator",
                "permissions": [],
                "claimed_role": "Direktur",
                "_workflow_context": None,
            },
        )()
    )


async def test_duplicate_bypass_idempotent(case):
    async with get_session_factory()() as session:
        user, job = await ctx(case, session)
        await enable_bypass_setting(session, user)
        first = await engine.bypass_payment(
            session, user, job, reason="same reason", idempotency_key="bypass-dup-1"
        )
    async with get_session_factory()() as session:
        user, job = await ctx(case, session)
        second = await engine.bypass_payment(
            session, user, job, reason="same reason", idempotency_key="bypass-dup-1"
        )
        assert first.id == second.id
        assert await session.scalar(select(func.count()).select_from(PaymentBypass)) == 1
        assert await session.scalar(
            select(func.count()).select_from(ProductionEvent).where(
                ProductionEvent.event_type == "payment_bypass_authorized"
            )
        ) == 1


async def test_bypass_does_not_invent_outstanding(case):
    async with get_session_factory()() as session:
        user, job = await ctx(case, session)
        await enable_bypass_setting(session, user)
        await engine.bypass_payment(
            session, user, job, reason="tempo", idempotency_key="bypass-out-1"
        )
        item = (await engine.list_payment_receipts(session, user, q="SO-F2-001"))["items"][0]
        assert item["payment_status"] == "bypassed"
        assert item["bypass_active"] is True
        assert item["outstanding_amount"] is None
        assert item["financial_settlement_known"] is False
        assert item["bypasses"][0]["gate_before"] == "pending"


async def test_production_before_reversal_sets_financial_exception(case):
    rid, *_ = await record(case, idempotency_key="f2-exc-1")
    async with get_session_factory()() as session:
        user, job = await ctx(case, session)
        session.add(
            ProductionEvent(
                job_id=job.id,
                event_type="output_confirmed",
                actor_user_id=user.id,
                qty_physical=Decimal("12"),
                idempotency_key="f2-output-1",
            )
        )
        await session.commit()
        await engine.invalidate_receipt(session, user, rid, reason="Accurate reversed")
        assert job.payment_status == "pending"
        assert job.payment_review_required is True
        assert await session.scalar(
            select(func.count()).select_from(ProductionEvent).where(
                ProductionEvent.event_type == "payment_financial_exception"
            )
        ) == 1
        # Physical history preserved
        assert await session.scalar(
            select(ProductionEvent.qty_physical).where(
                ProductionEvent.idempotency_key == "f2-output-1"
            )
        ) == Decimal("12")
        item = (await engine.list_payment_receipts(session, user, review_required=True))["items"][0]
        assert item["payment_review_required"] is True
        assert item["so_number"] == "SO-F2-001"


async def test_date_filter_uses_paid_at(case):
    await record(case, idempotency_key="f2-date-1")
    async with get_session_factory()() as session:
        user, _ = await ctx(case, session)
        start = datetime(2026, 11, 9, tzinfo=UTC)
        end = datetime(2026, 11, 11, tzinfo=UTC)
        hit = await engine.list_payment_receipts(
            session, user, q="SO-F2-001", date_from=start, date_to=end
        )
        miss = await engine.list_payment_receipts(
            session,
            user,
            q="SO-F2-001",
            date_from=datetime(2026, 1, 1, tzinfo=UTC),
            date_to=datetime(2026, 1, 2, tzinfo=UTC),
        )
        assert hit["total"] == 1
        assert miss["total"] == 0


async def test_concurrent_receipt_writes_single_row(case):
    rows = await asyncio.gather(record(case), record(case))
    assert rows[0][0] == rows[1][0]
    async with get_session_factory()() as session:
        assert await session.scalar(select(func.count()).select_from(PaymentReceiptRef)) == 1
