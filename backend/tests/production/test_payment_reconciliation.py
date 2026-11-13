import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func, event
from sqlalchemy.exc import IntegrityError
from tests.production.test_payment_p0 import case, context, record, schedule
from app.db.session import get_session_factory
from app.models.production.payment import PaymentReceiptRef
from app.models.production.event import ProductionEvent
from app.models.production.job import ProductionJob
from app.services.production import engine
from app.services.production.payment_gate import effective_status
from app.api.production.workflow import _job_summary
from app.api import customer_portal

async def revalidate(case, rid, key='revalidation-request-1'):
    async with get_session_factory()() as session:
        user, _ = await context(case, session)
        return await engine.revalidate_receipt(session, user, rid, reason='Owner review', idempotency_key=key)

async def test_all_read_models_ignore_legacy_mirror_without_writing(case, monkeypatch):
    async with get_session_factory()() as session:
        user, job = await context(case, session)
        user.permissions = list(user.permissions) + ['production.job.read']
        job.payment_status = 'approved'
        session.add(PaymentReceiptRef(job_id=job.id, accurate_receipt_id='900', amount=10, evidence_verified=False, recorded_by=user.id))
        await session.commit()
        assert (await _job_summary(job, session))['payment_status'] == 'pending'
        assert (await engine.job_board(session, user, job))['job']['payment_status'] == 'pending'
        assert (await engine.list_team_tasks(session, user))['jobs'][0]['payment_status'] == 'pending'
        async def resolve(*args, **kwargs):
            return SimpleNamespace(scope=customer_portal.CT.SCOPE_LIVE_TRACKING), job
        monkeypatch.setattr(customer_portal.CT, 'resolve_token', resolve)
        data = await customer_portal.customer_token_json('customer', 'po', 'token', session)
        assert json.loads(data.body)['payment_status'] == 'pending'
        assert data.headers['cache-control'] == 'no-store'
        page = await customer_portal.customer_token_page('customer', 'po', 'token', None, session)
        assert b'Payment: pending' in page.body
        assert job.payment_status == 'approved' and not session.dirty
    with pytest.raises(HTTPException):
        await schedule(case)

async def test_legacy_requires_explicit_reverification(case):
    async with get_session_factory()() as session:
        user, job = await context(case, session)
        row = PaymentReceiptRef(job_id=job.id, accurate_receipt_id='900', amount=999, evidence_verified=False, recorded_by=user.id)
        session.add(row); await session.commit(); rid = row.id
    result = await revalidate(case, rid)
    assert result['verified'] and result['amount'] == '125.50' and result['source'] == 'fixture'
    assert result['before'] == {'verified': False, 'amount': '999.00'}
    assert (await revalidate(case, rid))['replayed']
    async with get_session_factory()() as session:
        assert await effective_status(session, case[1]) == 'approved'
        assert await session.scalar(select(func.count()).select_from(ProductionEvent).where(ProductionEvent.event_type == 'payment_receipt_revalidated')) == 1

@pytest.mark.parametrize('patch', [{'status': 'VOID'}, {'amount': '0'}, {'sales_order_id': 'other'}, {'verifiable': False}])
async def test_revalidation_rejects_and_preserves_output(case, patch):
    rid, _, _ = await record(case)
    async with get_session_factory()() as session:
        session.add(ProductionEvent(job_id=case[1], event_type='output_confirmed', actor_user_id=case[0], qty_physical=25, idempotency_key='history-reconcile'))
        await session.commit()
    case[2].update(patch)
    result = await revalidate(case, rid)
    assert not result['verified'] and result['payment_status'] == 'pending'
    async with get_session_factory()() as session:
        row = await session.get(PaymentReceiptRef, rid)
        assert row.status == 'valid' and not row.evidence_verified and row.amount == Decimal('125.50')
        assert (await session.scalar(select(ProductionEvent).where(ProductionEvent.idempotency_key == 'history-reconcile'))).qty_physical == 25
    with pytest.raises(HTTPException): await schedule(case)

async def test_revalidation_outage_and_bypass(case, monkeypatch):
    rid, _, _ = await record(case)
    async with get_session_factory()() as session:
        user, job = await context(case, session)
        await engine.bypass_payment(session, user, job, reason='Approved exception')
    async def unavailable(*args, **kwargs): raise HTTPException(503, 'Unavailable')
    monkeypatch.setattr('app.services.accurate_evidence.require_valid_receipt', unavailable)
    result = await revalidate(case, rid)
    assert result['verification_error'] == 'source_unavailable' and result['payment_status'] == 'bypassed'

async def test_revalidation_schedule_concurrent_failure(case, monkeypatch):
    from app.services import accurate_evidence
    rid, _, _ = await record(case)
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed(*args, **kwargs):
        entered.set(); await release.wait(); raise HTTPException(409, 'Cancelled')
    monkeypatch.setattr(accurate_evidence, 'require_valid_receipt', delayed)
    task = asyncio.create_task(revalidate(case, rid))
    await asyncio.wait_for(entered.wait(), 3)
    assignment = asyncio.create_task(schedule(case))
    try:
        with pytest.raises(TimeoutError): await asyncio.wait_for(asyncio.shield(assignment), .1)
    finally: release.set()
    assert not (await task)['verified']
    with pytest.raises(HTTPException): await assignment

async def test_audit_failure_rolls_back_revalidation(case):
    rid, _, _ = await record(case)
    case[2]['status'] = 'VOID'
    def fail(mapper, connection, target):
        if target.event_type == 'payment_receipt_revalidated': raise RuntimeError('Injected audit failure')
    event.listen(ProductionEvent, 'before_insert', fail)
    try:
        with pytest.raises(RuntimeError): await revalidate(case, rid)
    finally: event.remove(ProductionEvent, 'before_insert', fail)
    async with get_session_factory()() as session:
        assert (await session.get(PaymentReceiptRef, rid)).evidence_verified
        assert await effective_status(session, case[1]) == 'approved'

async def test_revalidation_replay_does_not_report_invalidated_receipt_as_verified(case):
    rid, _, _ = await record(case)
    assert (await revalidate(case, rid))['verified']
    async with get_session_factory()() as session:
        user, _ = await context(case, session)
        await engine.invalidate_receipt(session, user, rid, reason='Cancelled after verification')
    replay = await revalidate(case, rid)
    assert replay['replayed'] and not replay['verified'] and replay['payment_status'] == 'pending'
    with pytest.raises(HTTPException): await revalidate(case, rid, key='new-request-invalidated')

async def test_revalidation_permission_and_request_collision(case):
    rid, _, _ = await record(case)
    async with get_session_factory()() as session:
        user, _ = await context(case, session)
        user.permissions = []
        with pytest.raises(HTTPException) as error:
            await engine.revalidate_receipt(session, user, rid, reason='Denied', idempotency_key='negative-request')
        assert error.value.status_code == 403
    await revalidate(case, rid)
    async with get_session_factory()() as session:
        user, _ = await context(case, session)
        with pytest.raises(HTTPException) as error:
            await engine.revalidate_receipt(session, user, rid, reason='Different request', idempotency_key='revalidation-request-1')
        assert error.value.status_code == 409
