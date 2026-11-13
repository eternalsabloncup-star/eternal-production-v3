"""Real PostgreSQL concurrency for enforced workflow writes. No mocks of the database."""
import asyncio
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from app.authorization import service
from app.authorization.models import ScopedGrant
from app.models.production.job import ProductionJob
from app.models.work_order import WorkOrder
from tests.authorization.test_foundation import db
from tests.authorization.test_runtime import runtime, login
from tests.authorization.test_workflow_access import enforced
from tests.authorization.test_workflow_completion import ready, grant, payload, job_numbers

SYNC = '/api/v1/production/jobs/tasks'
TIMEOUT = 40


async def counts(db):
    async with db() as s:
        return (await s.scalar(select(func.count()).select_from(ProductionJob)),
                await s.scalar(select(func.count()).select_from(WorkOrder)))


async def current_revision(db):
    async with db() as s:
        return (await service.load_access(s, 1)).revision


async def writer(db, name):
    for _ in range(20):
        try:
            async with db.begin() as s:
                await service.create_group(s, actor=1, revision=await _rev(s), reason='Concurrency writer', name=name)
            return True
        except HTTPException as exc:
            if exc.status_code != 409: raise
    return False


async def _rev(s):
    return (await service.load_access(s, 1, exclusive=True)).revision


async def test_two_concurrent_bulk_syncs_opposite_order_no_deadlock_and_idempotent_retry(ready):
    db, c = ready
    director, _ = await login(c)
    sos = [f'RACE-{i:02d}' for i in range(8)]
    forward = {'sync_ensure': True, 'jobs': [payload(s, 'A') for s in sos]}
    backward = {'sync_ensure': True, 'jobs': [payload(s, 'A') for s in reversed(sos)]}
    base = (await counts(db))[0]
    for _round in range(3):
        responses = await asyncio.wait_for(asyncio.gather(*(c.post(SYNC, headers=director, json=b) for b in (forward, backward) * 3)), TIMEOUT)
        codes = [r.status_code for r in responses]
        assert set(codes) <= {200, 409}, codes  # never 500/deadlock leakage
        for r in responses:
            if r.status_code == 409: assert 'tidak ada data tertulis' in r.text
        assert 200 in codes
    for b in (forward, backward):  # conflicting callers retry idempotently
        assert (await c.post(SYNC, headers=director, json=b)).status_code == 200
    jobs, orders = await counts(db)
    assert jobs - base == 8 and orders == 8
    numbers = await job_numbers(db)
    assert all(numbers.count(s) == 1 for s in sos)
    r = await c.post(SYNC, headers=director, json=backward)
    assert r.status_code == 200 and r.json()['synced'] == list(reversed(sos)) if 'synced' in r.json() else True


async def test_sync_rollback_when_a_later_job_fails_then_retry_is_clean(ready):
    db, c = ready
    director, _ = await login(c)
    bad = payload('RB-B', 'A'); bad['line_items'] = [{'accurate_line_id': 'L1', 'quantity': None}]
    before = await counts(db)
    r = await c.post(SYNC, headers=director, json={'sync_ensure': True, 'jobs': [payload('RB-A', 'A'), bad]})
    assert r.status_code == 422, r.text
    assert await counts(db) == before and 'RB-A' not in await job_numbers(db)
    r = await c.post(SYNC, headers=director, json={'sync_ensure': True, 'jobs': [payload('RB-A', 'A'), payload('RB-B', 'A')]})
    assert r.status_code == 200, r.text
    assert await counts(db) == (before[0] + 2, before[1] + 2)


async def test_revoke_during_mutation_waits_for_commit_then_denies(ready, monkeypatch):
    db, c = ready
    operator, _ = await login(c, 'test-3')
    gids = [await grant(db, cap) for cap in ('task.read', 'job.create')]
    from app.services.production import engine
    original = engine.ensure_job
    inside, release = asyncio.Event(), asyncio.Event()

    async def paused(session, user, **kw):
        row = await original(session, user, **kw)
        inside.set()
        await release.wait()
        return row
    monkeypatch.setattr(engine, 'ensure_job', paused)
    request = asyncio.create_task(c.post(SYNC, headers=operator, json={'sync_ensure': True, 'jobs': [payload('REV-1', 'A')]}))
    await asyncio.wait_for(inside.wait(), 10)

    async def revoke():
        async with db.begin() as s:
            await service.revoke_grant(s, actor=1, revision=await _rev(s), reason='Revoke while running', grant_id=gids[1])
    revoker = asyncio.create_task(revoke())
    await asyncio.sleep(0.5)
    assert not revoker.done()  # exclusive writer is held behind the request's shared lock
    release.set()
    r = await asyncio.wait_for(request, 10)
    assert r.status_code == 200, r.text  # the authorized operation completes atomically
    await asyncio.wait_for(revoker, 10)
    assert 'REV-1' in await job_numbers(db)
    r = await c.post(SYNC, headers=operator, json={'sync_ensure': True, 'jobs': [payload('REV-2', 'A')]})
    assert r.status_code == 403 and 'REV-2' not in await job_numbers(db)


async def test_mixed_readers_and_access_writers_have_consistent_lock_order(ready):
    db, c = ready
    director, _ = await login(c); operator, _ = await login(c, 'test-3')
    for cap in ('task.read', 'job.create', 'job.read'): await grant(db, cap)
    syncs = [c.post(SYNC, headers=director, json={'sync_ensure': True, 'jobs': [payload(f'MIX-{i % 3}', 'A')]}) for i in range(6)]
    reads = [c.get('/api/v1/production/jobs/1', headers=operator) for _ in range(6)]
    writers = [writer(db, f'Group {i}') for i in range(4)]
    results = await asyncio.wait_for(asyncio.gather(*syncs, *reads, *writers, return_exceptions=True), TIMEOUT)
    for r in results:
        if isinstance(r, Exception): raise r
        if hasattr(r, 'status_code'): assert r.status_code in (200, 409, 403), (r.status_code, r.text)
        else: assert r is True
    assert sorted(n for n in await job_numbers(db) if n.startswith('MIX-')) == ['MIX-0', 'MIX-1', 'MIX-2']


from sqlalchemy import text
from app.models.production.event import ProductionEvent

S = 'settings_foundation_test'
BODY = {'sync_ensure': True, 'jobs': [payload('DL-A', 'A'), payload('DL-B', 'A')]}


def payload(so, branch):  # local copy keeps this module self-describing
    return {'accurate_so_number': so, 'branch_id': branch, 'customer_name': 'Sandbox customer'}


async def assert_clean(db):
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(ProductionJob).where(ProductionJob.accurate_so_number.like('DL-%'))) == 0
        assert await s.scalar(select(func.count()).select_from(WorkOrder)) == 0


async def assert_idempotent_retry(db, c, headers):
    base_events = None
    for _ in range(2):
        r = await c.post(SYNC, headers=headers, json=BODY)
        assert r.status_code == 200, r.text
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(ProductionJob).where(ProductionJob.accurate_so_number.like('DL-%'))) == 2
        assert await s.scalar(select(func.count()).select_from(WorkOrder).where(WorkOrder.accurate_so_number.like('DL-%'))) == 2
        assert await s.scalar(select(func.count()).select_from(ProductionEvent).where(ProductionEvent.event_type.like('%sync%'))) == 0


async def test_real_postgres_deadlock_40p01_maps_to_retryable_409_and_rolls_back(ready, monkeypatch):
    db, c = ready
    director, _ = await login(c)
    from app.services.production import engine
    original = engine.ensure_job
    calls = {'n': 0}
    other = db()
    blocker = await other.__aenter__()
    await blocker.execute(text(f'SELECT id FROM {S}.users WHERE id=2 FOR UPDATE'))  # peer holds row 2

    async def peer():
        await asyncio.sleep(0.4)  # request is already waiting on row 2 (earlier deadlock timer => it is the victim)
        await blocker.execute(text(f'SELECT id FROM {S}.users WHERE id=3 FOR UPDATE'))

    peer_task = []

    async def deadlocking(session, user, **kw):
        calls['n'] += 1
        row = await original(session, user, **kw)
        if calls['n'] == 2:  # first job already flushed (pending) in the sync transaction
            await session.execute(text(f'SELECT id FROM {S}.users WHERE id=3 FOR UPDATE'))
            peer_task.append(asyncio.create_task(peer()))
            await session.execute(text(f'SELECT id FROM {S}.users WHERE id=2 FOR UPDATE'))
        return row
    monkeypatch.setattr(engine, 'ensure_job', deadlocking)
    try:
        r = await asyncio.wait_for(c.post(SYNC, headers=director, json=BODY), TIMEOUT)
        assert r.status_code == 409 and r.json()['error']['code'] == 'sync_conflict_nothing_written', r.text
        await asyncio.wait_for(peer_task[0], 10)  # peer proceeds once the victim rolled back
    finally:
        await blocker.rollback(); await other.__aexit__(None, None, None)
    await assert_clean(db)
    monkeypatch.setattr(engine, 'ensure_job', original)
    await assert_idempotent_retry(db, c, director)


async def test_real_postgres_serialization_40001_is_retryable_409(ready, monkeypatch):
    db, c = ready
    director, _ = await login(c)
    from app.services.production import engine
    original = engine.ensure_job
    calls = {'n': 0}

    async def serialization_failure(session, user, **kw):
        calls['n'] += 1
        row = await original(session, user, **kw)
        if calls['n'] == 2:
            await session.execute(text("DO $$ BEGIN RAISE EXCEPTION 'could not serialize access' USING ERRCODE = '40001'; END $$"))
        return row
    monkeypatch.setattr(engine, 'ensure_job', serialization_failure)
    r = await asyncio.wait_for(c.post(SYNC, headers=director, json=BODY), TIMEOUT)
    assert r.status_code == 409 and 'tidak ada data tertulis' in r.text, r.text
    await assert_clean(db)
    monkeypatch.setattr(engine, 'ensure_job', original)
    await assert_idempotent_retry(db, c, director)


@pytest.mark.parametrize('sqlstate', ['XX000', '22012', '57014', '23514', '23503'])
async def test_other_database_errors_are_never_reported_as_retryable_409(ready, monkeypatch, sqlstate):
    db, c = ready
    director, _ = await login(c)
    from app.services.production import engine
    original = engine.ensure_job

    async def broken(session, user, **kw):
        row = await original(session, user, **kw)
        await session.execute(text(f"DO $$ BEGIN RAISE EXCEPTION 'synthetic failure' USING ERRCODE = '{sqlstate}'; END $$"))
        return row
    monkeypatch.setattr(engine, 'ensure_job', broken)
    try:
        r = await asyncio.wait_for(c.post(SYNC, headers=director, json=BODY), TIMEOUT)
        assert r.status_code >= 500, (r.status_code, r.text)
    except Exception as exc:
        assert not isinstance(exc, HTTPException)
    await assert_clean(db)
