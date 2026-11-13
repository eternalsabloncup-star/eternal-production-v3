"""Payment P0: offline gateway doubles + isolated PostgreSQL, never Accurate Live."""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.models.production.event import ProductionEvent
from app.models.production.job import ProductionJob
from app.models.production.payment import PaymentReceiptRef
from app.models.user import User
from app.services import accurate_evidence
from app.services.production import engine, permissions as P


@pytest.fixture
async def case(monkeypatch):
    # The parent conftest resolves only dedicated test DB names. Tests are run
    # with explicit localhost TEST_DATABASE_URL, never inherited Live settings.
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_session_factory()() as session:
        user = User(username="payment-test", display_name="Test", role="operator",
                    password_hash="unused", branch_ids=["BR-JKT"],
                    permissions=[P.PAYMENT_RECORD, P.PAYMENT_BYPASS, P.PAYMENT_REVOKE,
                                 P.SCHEDULE_MANAGE])
        job = ProductionJob(accurate_so_number="SO-LIVE-001", accurate_id="700",
                            branch_id="BR-JKT", design_status="bypassed")
        session.add_all([user, job])
        await session.commit()
        uid, jid = user.id, job.id

    # Explicit offline test double, not application fixtures or a Live call.
    payload = dict(id="900", number="RCP-900", sales_order_number="SO-LIVE-001",
                   sales_order_id="700", branch={"id": "BR-JKT"}, amount="125.50",
                   status="POSTED", cancelled=False, reversed=False,
                   verifiable=True, source="fixture", live_verified=False)

    class Gateway:
        async def get(self, path, **kwargs):
            return dict(payload)

    monkeypatch.setattr(accurate_evidence, "ReadGateway", Gateway)
    return uid, jid, payload


async def context(case, session):
    return await session.get(User, case[0]), await session.get(ProductionJob, case[1])


async def record(case, **kwargs):
    async with get_session_factory()() as session:
        user, job = await context(case, session)
        row = await engine.record_payment_receipt(
            session, user, job, accurate_receipt_id="RCP-900", **kwargs
        )
        return row.id, row.amount, job.payment_status


def schedule_args():
    return dict(so_line_id="line-1", product_id=None, color_pass=1,
                operator_name="Test", machine_name="Test", work_date=date(2026, 11, 14),
                qty_planned=Decimal("1"))


async def schedule(case):
    async with get_session_factory()() as session:
        user, job = await context(case, session)
        return await engine.create_assignment(session, user, job, **schedule_args())


async def test_official_partial_payment_ignores_frontend_amount(case):
    rid, amount, status = await record(case, amount=Decimal("999999"))
    assert amount == Decimal("125.50") and status == "approved"
    async with get_session_factory()() as session:
        assert await session.scalar(select(func.count()).select_from(ProductionEvent).where(
            ProductionEvent.event_type == "payment_receipt_verified")) == 1
        job = await session.get(ProductionJob, case[1])
        assert job.design_status == "bypassed"


async def test_exact_gateway_decimal_is_authoritative(case):
    case[2].update(amount=125.5, amount_decimal="125.51")
    assert (await record(case))[1] == Decimal("125.51")


async def test_zero_decimal_cannot_fall_back_to_positive_numeric(case):
    case[2].update(amount=125.5, amount_decimal="0")
    with pytest.raises(HTTPException) as exc:
        await record(case)
    assert exc.value.status_code == 409


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", None, True, "0.001"])
async def test_ineffective_amount_rejected(case, amount):
    case[2]["amount"] = amount
    with pytest.raises(HTTPException) as exc:
        await record(case, amount=Decimal("500"))
    assert exc.value.status_code == 409


@pytest.mark.parametrize("status", ["VOID", "CANCELLED", "REVERSED", "UNKNOWN", "", "DRAFT", "UNMAPPED"])
async def test_void_unknown_rejected(case, status):
    case[2]["status"] = status
    with pytest.raises(HTTPException) as exc:
        await record(case)
    assert exc.value.status_code == 409


@pytest.mark.parametrize("field,value", [
    ("sales_order_number", "SO-OTHER"), ("sales_order_id", "701"),
    ("sales_order_id", None), ("branch", {}), ("verifiable", False),
    ("source", "untrusted"), ("id", ""),
])
async def test_wrong_ambiguous_unverified_evidence_rejected(case, field, value):
    case[2][field] = value
    with pytest.raises(HTTPException) as exc:
        await record(case)
    assert exc.value.status_code == 409


async def test_fixture_rejected_outside_test(case, monkeypatch):
    monkeypatch.setattr(accurate_evidence, "get_settings", lambda: type("Settings", (), {"app_env": "staging"})())
    with pytest.raises(HTTPException) as exc:
        await record(case)
    assert exc.value.status_code == 409


async def test_verified_live_contract_accepted_without_live_network(case, monkeypatch):
    case[2].update(source="accurate_live", live_verified=True)
    monkeypatch.setattr(accurate_evidence, "get_settings", lambda: type("Settings", (), {"app_env": "staging"})())
    assert (await record(case))[2] == "approved"


async def test_duplicate_alias_and_request_idempotent(case):
    first = await record(case, idempotency_key="payment-request-1")
    second = await record(case, idempotency_key="payment-request-1")
    async with get_session_factory()() as session:
        user, job = await context(case, session)
        alias = await engine.record_payment_receipt(session, user, job, accurate_receipt_id="900")
        assert first[0] == second[0] == alias.id
        assert await session.scalar(select(func.count()).select_from(PaymentReceiptRef)) == 1
    case[2]["id"] = "901"
    with pytest.raises(HTTPException) as exc:
        await record(case, idempotency_key="payment-request-1")
    assert exc.value.status_code == 409


async def test_concurrent_duplicate_has_one_active_evidence(case):
    rows = await asyncio.gather(record(case), record(case))
    assert rows[0][0] == rows[1][0]
    async with get_session_factory()() as session:
        assert await session.scalar(select(func.count()).select_from(PaymentReceiptRef)) == 1
        session.add(PaymentReceiptRef(job_id=case[1], accurate_receipt_id="900", status="valid"))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_bypass_permission_and_reason(case):
    async with get_session_factory()() as session:
        user, job = await context(case, session)
        user.permissions = []
        with pytest.raises(HTTPException) as exc:
            await engine.bypass_payment(session, user, job, reason="not allowed")
        assert exc.value.status_code == 403
        await session.rollback()
    async with get_session_factory()() as session:
        user, job = await context(case, session)
        with pytest.raises(HTTPException) as exc:
            await engine.bypass_payment(session, user, job, reason=" ")
        assert exc.value.status_code == 422


async def test_revoke_one_bypass_preserves_other_and_audit(case):
    async with get_session_factory()() as session:
        user, job = await context(case, session)
        first = await engine.bypass_payment(session, user, job, reason="first authorized exception")
        await engine.bypass_payment(session, user, job, reason="second authorized exception")
        await engine.revoke_payment_bypass(session, user, first.id, reason="first no longer needed")
        assert job.payment_status == "bypassed"
        assert await session.scalar(select(func.count()).select_from(ProductionEvent).where(
            ProductionEvent.event_type == "payment_bypass_authorized")) == 2


async def test_print_design_pending_blocks_schedule(case):
    await record(case)
    async with get_session_factory()() as session:
        job = await session.get(ProductionJob, case[1])
        job.design_status = "pending"
        await session.commit()
    with pytest.raises(HTTPException) as exc:
        await schedule(case)
    assert exc.value.status_code == 409


async def test_no_receipt_blocks_schedule_even_if_mirror_approved(case):
    async with get_session_factory()() as session:
        job = await session.get(ProductionJob, case[1])
        job.payment_status = "approved"
        await session.commit()
    with pytest.raises(HTTPException) as exc:
        await schedule(case)
    assert exc.value.status_code == 409


async def test_payment_schedule_serialized(case, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowGateway:
        async def get(self, path, **kwargs):
            entered.set()
            await release.wait()
            return dict(case[2])

    monkeypatch.setattr(accurate_evidence, "ReadGateway", SlowGateway)
    payment = asyncio.create_task(record(case))
    await asyncio.wait_for(entered.wait(), 5)
    assignment = asyncio.create_task(schedule(case))
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(assignment), .1)
    finally:
        release.set()
    await asyncio.wait_for(payment, 5)
    assert (await asyncio.wait_for(assignment, 5)).job_id == case[1]


async def test_invalidation_preserves_output_and_replay_does_not_reopen(case):
    rid, _, _ = await record(case, idempotency_key="payment-history-1")
    async with get_session_factory()() as session:
        user, job = await context(case, session)
        event = ProductionEvent(job_id=job.id, event_type="output_confirmed",
                                actor_user_id=user.id, qty_physical=Decimal("25"),
                                idempotency_key="historical-output-1")
        session.add(event)
        await session.commit()
        eid = event.id
        await engine.invalidate_receipt(session, user, rid, reason="receipt invalidated")
        assert job.payment_status == "pending"
        output = await session.get(ProductionEvent, eid)
        assert output.qty_physical == Decimal("25")
        assert output.event_type == "output_confirmed"
    replay = await record(case, idempotency_key="payment-history-1")
    assert replay[0] == rid and replay[2] == "pending"
    with pytest.raises(HTTPException):
        await schedule(case)


async def test_gateway_failure_never_approves(case, monkeypatch):
    class FailedGateway:
        async def get(self, path, **kwargs):
            raise HTTPException(503, "offline test upstream failure")
    monkeypatch.setattr(accurate_evidence, "ReadGateway", FailedGateway)
    with pytest.raises(HTTPException) as exc:
        await record(case)
    assert exc.value.status_code == 503
    async with get_session_factory()() as session:
        assert (await session.get(ProductionJob, case[1])).payment_status == "pending"
        assert await session.scalar(select(func.count()).select_from(PaymentReceiptRef)) == 0


async def test_nonprint_keeps_design_exception(case):
    from app.models.production.prep import JobLineQty
    await record(case)
    async with get_session_factory()() as session:
        user, job = await context(case, session)
        job.design_status = "pending"
        session.add(JobLineQty(job_id=job.id, so_line_id="line-1", po_qty=10,
                               production_process="non_print"))
        await session.commit()
    assert (await schedule(case)).job_id == case[1]


async def test_invalidation_serializes_stale_schedule_and_preserves_gate(case):
    rid, _, _ = await record(case)
    async with get_session_factory()() as invalidating, get_session_factory()() as scheduling:
        user, stale_job = await context(case, scheduling)
        # Load an approved job before the invalidation to exercise populate_existing.
        assert stale_job.payment_status == "approved"
        actor, job = await context(case, invalidating)
        await engine._lock_payment_job(invalidating, actor, job)
        pending = asyncio.create_task(engine.create_assignment(scheduling, user, stale_job, **schedule_args()))
        try:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(pending), .1)
        finally:
            await engine.invalidate_receipt(invalidating, actor, rid, reason="official receipt invalidated")
        with pytest.raises(HTTPException) as exc:
            await asyncio.wait_for(pending, 5)
        assert exc.value.status_code == 409
        await scheduling.rollback()


async def test_branch_scope_and_revoke_reason(case):
    async with get_session_factory()() as session:
        user, job = await context(case, session)
        bypass = await engine.bypass_payment(session, user, job, reason="authorized exception")
        with pytest.raises(HTTPException) as exc:
            await engine.revoke_payment_bypass(session, user, bypass.id, reason=" ")
        assert exc.value.status_code == 422
        user.branch_ids = []
        with pytest.raises(HTTPException) as exc:
            await engine.bypass_payment(session, user, job, reason="wrong branch")
        assert exc.value.status_code == 403
