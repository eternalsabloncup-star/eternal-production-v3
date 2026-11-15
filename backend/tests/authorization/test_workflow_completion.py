"""Settings & Permission completion: bulk sync, revision fence, inbox scope, payroll
documents, full endpoint matrix and read-only inventory. Isolated PostgreSQL only."""
import re
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from app.core.errors import AppError
from sqlalchemy import select, func, text

from app.authorization.catalog import CATALOG
from app.authorization.models import AccessState, ScopedGrant, AccessAudit
from app.authorization.workflow import install_revision_fence
from app.authorization.workflow_map import WORKFLOW, INBOX, PAYROLL
from app.models.production.job import ProductionJob
from app.models.production.payroll import PayrollRun, PayrollLine
from app.models.work_order import WorkOrder
from app.models.user import User
from tests.authorization.test_foundation import db
from tests.authorization.test_runtime import runtime, login
from tests.authorization.test_workflow_access import enforced

SCHEMA = 'settings_foundation_test'
MAPPING = {**WORKFLOW, **PAYROLL, **INBOX}


async def grant(db, cap, branches=('A',), ownership='all'):
    branches = [] if CATALOG[cap].scope == 'global' else list(branches)
    async with db.begin() as s:
        g = ScopedGrant(group_id=2, capability=cap, branches=branches, ownership=ownership, assignments=[], active=True)
        s.add(g); await s.flush(); return g.id


async def bump_revision(db):
    async with db.begin() as s:
        state = await s.get(AccessState, 1)
        state.revision += 1


@pytest.fixture
async def ready(enforced):
    db, c = enforced
    async with db.begin() as s:
        await s.execute(text(f"SELECT setval('{SCHEMA}.production_jobs_id_seq', 100, true)"))
        await s.execute(text(f"SELECT setval('{SCHEMA}.schedule_assignments_id_seq', 100, true)"))
    return db, c


def payload(so, branch):
    return {'accurate_so_number': so, 'branch_id': branch, 'customer_name': 'Sandbox customer'}


async def job_numbers(db):
    async with db() as s:
        return sorted((await s.scalars(select(ProductionJob.accurate_so_number))).all())


async def test_bulk_sync_single_transaction_idempotent_director(ready):
    db, c = ready
    director, _ = await login(c)
    body = {'sync_ensure': True, 'jobs': [payload('SYNC-A1', 'A'), payload('SYNC-B1', 'B')]}
    r = await c.post('/api/v1/production/jobs/tasks', headers=director, json=body)
    assert r.status_code == 200, r.text
    assert await job_numbers(db) == ['ACCESS-1', 'ACCESS-2', 'SYNC-A1', 'SYNC-B1']
    r = await c.post('/api/v1/production/jobs/tasks', headers=director, json=body)
    assert r.status_code == 200, r.text
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(ProductionJob)) == 4
        assert await s.scalar(select(func.count()).select_from(WorkOrder)) == 2


async def test_bulk_sync_failure_leaves_no_partial_write(ready):
    db, c = ready
    operator, _ = await login(c, 'test-3')
    for cap in ('task.read', 'job.create'):
        await grant(db, cap)
    # ACCESS-2 exists in branch B; claiming it as A must fail the whole page.
    body = {'sync_ensure': True, 'jobs': [payload('SYNC-OK', 'A'), payload('ACCESS-2', 'A')]}
    r = await c.post('/api/v1/production/jobs/tasks', headers=operator, json=body)
    assert r.status_code == 403, r.text
    assert 'SYNC-OK' not in await job_numbers(db)
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(WorkOrder)) == 0


async def test_bulk_sync_requires_job_create_per_branch(ready):
    db, c = ready
    operator, _ = await login(c, 'test-3')
    await grant(db, 'task.read', ('A', 'B'))
    body = {'sync_ensure': True, 'jobs': [payload('SYNC-A2', 'A'), payload('SYNC-B2', 'B')]}
    r = await c.post('/api/v1/production/jobs/tasks', headers=operator, json=body)
    assert r.status_code == 403, r.text
    assert (await c.post('/api/v1/production/jobs/tasks', headers=operator, json={'so_numbers': ['ACCESS-1']})).status_code == 200
    await grant(db, 'job.create', ('A',))
    r = await c.post('/api/v1/production/jobs/tasks', headers=operator, json=body)
    assert r.status_code == 200, r.text
    numbers = await job_numbers(db)
    assert 'SYNC-A2' in numbers and 'SYNC-B2' not in numbers


async def test_revision_fence_stale_before_commit_writes_nothing_after_commit_reads_only(db):
    async with db() as s:
        install_revision_fence(s, 0)
        await s.scalar(select(User.id).limit(1))
        await s.commit()
        await s.scalar(select(User.id).limit(1))  # same revision: allowed, re-locks FOR SHARE
        await s.commit()
    async with db() as s:
        install_revision_fence(s, 0)
        await bump_revision(db)
        with pytest.raises(AppError) as exc:
            await s.scalar(select(User.id).limit(1))
        assert exc.value.status_code == 409 and exc.value.code == 'access_changed_nothing_written'
        await s.rollback()
    await bump_revision(db)
    async with db() as s:
        install_revision_fence(s, 2)
        await s.scalar(select(User.id).limit(1)); await s.commit()
        await bump_revision(db)
        assert await s.scalar(select(User.id).limit(1))  # read after a committed step must not 409
        (await s.get(User, 3)).display_name = 'late write'
        with pytest.raises(AppError) as exc:
            await s.flush()
        assert exc.value.status_code == 409 and exc.value.code == 'access_changed_reconcile'
        await s.rollback()


async def test_revision_fence_holds_writers_until_commit(db):
    import asyncio
    async with db() as reader:
        await reader.scalar(select(User.id).limit(1))
        install_revision_fence(reader, 0)
        await reader.commit()
        await reader.scalar(select(User.id).limit(1))  # new transaction holds FOR SHARE
        writer = asyncio.create_task(bump_revision(db))
        await asyncio.sleep(0.3)
        assert not writer.done()
        await reader.commit()
        await asyncio.wait_for(writer, 5)


async def test_fence_never_hides_committed_write_behind_409(ready, monkeypatch):
    db, c = ready
    director, _ = await login(c)
    from app.services.production import engine
    original = engine.list_team_tasks

    async def read_after_commit(session, user, **kw):
        await engine.ensure_job(session, user, accurate_so_number='FENCE-1', branch_id='A')  # commits
        await session.commit()  # no open transaction: a writer can slip in between steps
        await bump_revision(db)
        return await original(session, user, **kw)
    monkeypatch.setattr(engine, 'list_team_tasks', read_after_commit)
    r = await c.post('/api/v1/production/jobs/tasks', headers=director, json={'sync_ensure': True, 'jobs': []})
    assert r.status_code == 200, r.text  # committed step is reported, not hidden
    assert 'FENCE-1' in await job_numbers(db)

    async def write_after_stale(session, user, **kw):
        await engine.ensure_job(session, user, accurate_so_number='FENCE-2', branch_id='A')  # commits
        await session.commit()
        await bump_revision(db)
        await engine.ensure_job(session, user, accurate_so_number='FENCE-3', branch_id='A')
    monkeypatch.setattr(engine, 'list_team_tasks', write_after_stale)
    r = await c.post('/api/v1/production/jobs/tasks', headers=director, json={'sync_ensure': True, 'jobs': []})
    assert r.status_code == 409 and 'earlier step committed' in r.text
    assert r.json()['error']['code'] == 'access_changed_reconcile'
    numbers = await job_numbers(db)
    assert 'FENCE-2' in numbers and 'FENCE-3' not in numbers  # status is reconcilable from the message


class FakeGateway:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    async def get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        if path != '/sales-orders':
            return {'number': path.rsplit('/', 1)[1], 'branch_id': 'A', 'line_items': []}
        page, limit = params['page'], params['limit']
        return {'rows': self.rows[(page - 1) * limit: page * limit], 'total': len(self.rows)}


def gateway_rows():
    # 230 upstream rows; only every fifth row is branch A (46 total).
    return [{'number': f'SO-{i:03d}', 'branch_id': 'A' if i % 5 == 0 else 'B'} for i in range(230)]


async def test_inbox_scoped_pagination_never_leaks_other_branch_totals(ready, monkeypatch):
    db, c = ready
    from app.api.production_inbox import get_gateway
    fake = FakeGateway(gateway_rows())
    c._transport.app.dependency_overrides[get_gateway] = lambda: fake
    operator, _ = await login(c, 'test-3')
    await grant(db, 'inbox.read')
    pages = []
    for page in (1, 2, 3):
        r = await c.get(f'/api/v1/production/inbox?page={page}&limit=20', headers=operator)
        assert r.status_code == 200, r.text
        pages.append(r.json())
    assert [len(p['rows']) for p in pages] == [20, 20, 6]
    assert [p['has_more'] for p in pages] == [True, True, False]
    assert {row['branch_id'] for p in pages for row in p['rows']} == {'A'}
    assert len({row['po_number'] for p in pages for row in p['rows']}) == 46
    assert pages[2]['total'] == 46 and pages[2]['gateway_total'] == 46 and not pages[2]['scan_incomplete']
    director, _ = await login(c)
    r = await c.get('/api/v1/production/inbox?page=1&limit=20', headers=director)
    assert r.json()['total'] == 230 and len(r.json()['rows']) == 20


async def seed_payroll(db):
    async with db.begin() as s:
        runs = []
        for branch in ('A', 'B', None):
            run = PayrollRun(period_start=date(2026, 11, 1), period_end=date(2026, 11, 7), branch_id=branch,
                             status='finalized', idempotency_key=f'run-{branch}', created_by=1, rate_snapshot_json='{}')
            s.add(run); await s.flush(); runs.append(run.id)
            for line_branch in ([branch] if branch else ['A', 'B']):
                s.add(PayrollLine(run_id=run.id, operator_name=f'Operator {line_branch}', branch_id=line_branch,
                                  qty_one=Decimal('10'), amount_gross=Decimal('1000'), source_event_ids='[1]', rate_snapshot_json='{}'))
        return runs


@pytest.mark.parametrize('kind', ['payroll.print', 'payroll.export'])
async def test_payroll_documents_explicit_grant_and_branch_scope(ready, kind):
    db, c = ready
    run_a, run_b, run_all = await seed_payroll(db)
    operator, _ = await login(c, 'test-3'); director, _ = await login(c)
    url = f'/api/v1/production/access/documents/{kind}?run_id='
    await grant(db, 'payroll.run.read')
    assert (await c.get(url + str(run_a), headers=operator)).status_code == 403
    await grant(db, kind)
    r = await c.get(url + str(run_a), headers=operator)
    assert r.status_code == 200, r.text
    assert [i['branch_id'] for i in r.json()['items']] == ['A']
    assert 'source_event_ids' not in r.json()['items'][0]
    assert (await c.get(url + str(run_b), headers=operator)).status_code == 403
    r = await c.get(url + str(run_all), headers=operator)
    assert [i['branch_id'] for i in r.json()['items']] == ['A']
    assert (await c.get(url.split('?')[0], headers=operator)).status_code == 422
    r = await c.get(url + str(run_all), headers=director)
    assert sorted(i['branch_id'] for i in r.json()['items']) == ['A', 'B']


def matrix_routes():
    from app.api.production.workflow import router as w
    from app.api.production_inbox import router as i
    from app.api.production.payroll import router as p
    from app.api.production.operations import router as o
    return [(next(iter(r.methods)), '/api/v1' + r.path, r.endpoint.__name__) for router in (w, i, p, o) for r in router.routes]


def concrete(path, job=1, run=1):
    path = path.replace('{job_id}', str(job)).replace('{run_id}', str(run))
    return re.sub(r'\{[^}]+\}', '1', path)


def matrix_body(name, branch):
    if name in {'create_job', 'create_run'}:
        return {'branch_id': branch, 'idempotency_key': f'matrix-{branch}'}
    return {}


@pytest.fixture
async def matrix(ready, monkeypatch):
    db, c = ready
    monkeypatch.setenv('V3_ACCURATE_READ_GATEWAY_URL', '')
    monkeypatch.setenv('V3_ACCURATE_READ_GATEWAY_TOKEN', '')
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.services import accurate_read_gateway

    async def no_network(*a, **kw):
        raise HTTPException(503, 'Network disabled in sandbox matrix')
    monkeypatch.setattr(accurate_read_gateway.ReadGateway, 'get', no_network)
    from app.api.production_inbox import get_gateway
    c._transport.app.dependency_overrides[get_gateway] = lambda: FakeGateway(gateway_rows())
    async with db.begin() as s:
        for branch in ('A', 'B'):
            s.add(PayrollRun(period_start=date(2026, 11, 1), period_end=date(2026, 11, 7), branch_id=branch,
                             status='finalized', idempotency_key=f'seed-{branch}', created_by=1, rate_snapshot_json='{}'))
    return db, c


async def test_all_62_endpoints_director_full_access(matrix):
    _, c = matrix
    director, _ = await login(c)
    routes = matrix_routes()
    assert len(routes) == 62
    assert any(name == 'production_schedule_list' for _, _, name in routes)
    for method, path, name in routes:
        for job, run in ((1, 1), (2, 2)):
            r = await c.request(method, concrete(path, job, run), headers=director, json=matrix_body(name, 'B' if job == 2 else 'A'))
            assert r.status_code not in (401, 403), (name, job, r.status_code, r.text)


async def test_all_62_endpoints_scoped_allow_cross_branch_and_revocation_deny(matrix):
    db, c = matrix
    operator, _ = await login(c, 'test-3')
    checked = 0
    for method, path, name in matrix_routes():
        cap = MAPPING[name][0]
        r = await c.request(method, concrete(path), headers=operator, json=matrix_body(name, 'A'))
        assert r.status_code == 403, ('no grant', name, r.status_code)
        gid = await grant(db, cap)
        r = await c.request(method, concrete(path), headers=operator, json=matrix_body(name, 'A'))
        assert r.status_code not in (401, 403), ('scoped allow', name, r.status_code, r.text)
        cross_branch = '{job_id}' in path and path.count('{') == 1 or name in {'create_job', 'create_run', 'get_run'}
        if cross_branch and CATALOG[cap].scope == 'branch':
            r = await c.request(method, concrete(path, job=2, run=2), headers=operator, json=matrix_body(name, 'B'))
            assert r.status_code == 403, ('cross branch', name, r.status_code, r.text)
        async with db.begin() as s:
            (await s.get(ScopedGrant, gid)).active = False
        r = await c.request(method, concrete(path), headers=operator, json=matrix_body(name, 'A'))
        assert r.status_code == 403, ('revoked', name, r.status_code)
        async with db.begin() as s:
            await s.delete(await s.get(ScopedGrant, gid))
        checked += 1
    assert checked == 62


@pytest.mark.parametrize('actor', ['director', 'scoped'])
async def test_real_mutations_execute_under_enforced_mode(matrix, actor):
    db, c = matrix
    headers, _ = await login(c, 'test-1' if actor == 'director' else 'test-3')
    if actor == 'scoped':
        for cap in ('job.create', 'job.read', 'payment.bypass.create', 'payment.bypass.revoke',
                    'payroll.rate.manage', 'payroll.run.create', 'payroll.run.read'):
            await grant(db, cap)
    r = await c.post('/api/v1/production/jobs', headers=headers, json=payload('MUT-A', 'A'))
    assert r.status_code in (200, 201), r.text
    job_id = r.json()['id']
    assert (await c.get(f'/api/v1/production/jobs/{job_id}', headers=headers)).status_code == 200
    r = await c.post(f'/api/v1/production/jobs/{job_id}/payment/bypass', headers=headers, json={'reason': 'Sandbox approved bypass'})
    assert r.status_code in (200, 201), r.text
    bypass_id = r.json()['id']
    r = await c.post(f'/api/v1/production/jobs/payment/bypass/{bypass_id}/revoke', headers=headers, json={'reason': 'Sandbox revoke'})
    assert r.status_code in (200, 201), r.text
    r = await c.post('/api/v1/production/payroll/rates', headers=headers, json={'component': 'one', 'amount': '100', 'effective_from': '2026-11-01'})
    assert r.status_code in (200, 201), r.text
    r = await c.post('/api/v1/production/payroll/runs', headers=headers,
                     json={'period_start': '2026-11-01', 'period_end': '2026-11-07', 'branch_id': 'A', 'idempotency_key': 'mut-run-' + actor})
    assert r.status_code in (200, 201), r.text
    assert (await c.get(f"/api/v1/production/payroll/runs/{r.json()['id']}", headers=headers)).status_code == 200
    if actor == 'scoped':
        assert (await c.post('/api/v1/production/jobs', headers=headers, json=payload('MUT-B', 'B'))).status_code == 403
        assert (await c.post('/api/v1/production/jobs/2/payment/bypass', headers=headers, json={'reason': 'Other branch'})).status_code == 403
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(ProductionJob).where(ProductionJob.accurate_so_number == 'MUT-B')) == 0


async def test_inventory_report_is_read_only_and_flags_narrowing(ready):
    db, _ = ready
    from app.authorization import inventory
    await grant(db, 'output.record', ownership='own')
    async with db.begin() as s:
        u = await s.get(User, 3)
        u.permissions = ['production.output.confirm', 'production.invented']; u.branch_ids = ['A']
    async with db() as s:
        audits = await s.scalar(select(func.count()).select_from(AccessAudit))
        grants = await s.scalar(select(func.count()).select_from(ScopedGrant))
    async with db() as s:
        report = await inventory.build(s)
        with pytest.raises(Exception, match='read-only'):
            await s.execute(text(f'UPDATE {SCHEMA}.access_state SET revision = revision'))
        await s.rollback()
    rows = {r['user_id']: r for r in report['users']}
    operator = rows[3]
    assert operator['blocking'] and operator['unknown_legacy'] == ['production.invented']
    assert any(n['capability'] == 'output.record' and n['branch'] == 'A' for n in operator['narrowing'])
    assert rows[1]['director'] and not rows[1]['narrowing']
    assert report['blocking_user_ids'] == [3] and not report['cutover_review_clear']
    assert not report['automatic_import_allowed'] and not report['writes_performed']
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(AccessAudit)) == audits
        assert await s.scalar(select(func.count()).select_from(ScopedGrant)) == grants


async def test_inventory_cli_preflight_refuses_remote_and_hides_identity(ready, monkeypatch, capsys):
    from app.authorization import inventory
    db, _ = ready
    monkeypatch.setenv('DATABASE_URL', 'postgresql+asyncpg://u:secret-pw@db.example.invalid:5432/live')
    from app.core.config import get_settings
    get_settings.cache_clear()
    assert await inventory._main(['--preflight']) == 0
    out = capsys.readouterr().out
    assert 'secret-pw' not in out and '"connects": false' in out and '"loopback": false' in out
    assert await inventory._main(['--summary']) == 3  # refused before any connection
    async with db() as s:
        report = await inventory.build(s)
        await s.rollback()
    assert all('username' not in r for r in report['users'])
    summary = inventory.summarize(report)
    assert summary['writes_performed'] is False and 'users' not in summary
    get_settings.cache_clear()


class CountingGateway(FakeGateway):
    pass


async def inbox_as_operator(ready, rows, pages=(1,), limit=20, max_pages=None, monkeypatch=None):
    db, c = ready
    from app.api.production_inbox import get_gateway
    fake = CountingGateway(rows)
    c._transport.app.dependency_overrides[get_gateway] = lambda: fake
    if max_pages:
        monkeypatch.setenv('V3_INBOX_SCOPED_SCAN_MAX_PAGES', str(max_pages))
        from app.core.config import get_settings
        get_settings.cache_clear()
    operator, _ = await login(c, 'test-3')
    try:
        await grant(db, 'inbox.read')
    except Exception:
        pass
    out = []
    for p in pages:
        r = await c.get(f'/api/v1/production/inbox?page={p}&limit={limit}', headers=operator)
        assert r.status_code == 200, r.text
        out.append(r.json())
    return out, fake


async def test_inbox_large_volume_beyond_old_20_page_cap_is_exact(ready):
    rows = [{'number': f'BIG-{i:05d}', 'branch_id': 'A' if i % 50 == 0 else 'B'} for i in range(3000)]
    (p1, p2, p3), fake = await inbox_as_operator(ready, rows, pages=(1, 2, 3), limit=20)
    assert [len(p['rows']) for p in (p1, p2, p3)] == [20, 20, 20]
    assert p1['rows'][0]['po_number'] == 'BIG-00000' and p3['rows'][-1]['po_number'] == 'BIG-02950'
    assert p3['total'] == 60 and p3['has_more'] is False and p3['scan_incomplete'] is False  # exhausted: exact own-branch count
    assert max(call[1]['page'] for call in fake.calls if call[0] == '/sales-orders') <= 30


async def test_inbox_budget_limit_reports_incomplete_without_inventing_total(ready, monkeypatch):
    rows = [{'number': f'FAR-{i:05d}', 'branch_id': 'A' if i >= 2500 else 'B'} for i in range(3000)]
    (p1,), fake = await inbox_as_operator(ready, rows, pages=(1,), limit=20, max_pages=5, monkeypatch=monkeypatch)
    assert p1['rows'] == [] and p1['total'] is None and p1['gateway_total'] is None
    assert p1['scan_incomplete'] is True and p1['has_more'] is False
    assert len([c for c in fake.calls if c[0] == '/sales-orders']) == 5  # bounded, never unbounded
    assert '3000' not in str(p1)  # upstream (cross-branch) volume is not disclosed
    (q1,), _ = await inbox_as_operator(ready, rows, pages=(1,), limit=20, max_pages=30, monkeypatch=monkeypatch)
    assert len(q1['rows']) == 20 and q1['rows'][0]['po_number'] == 'FAR-02500'


async def test_inbox_empty_and_past_end_pages(ready):
    rows = [{'number': f'E-{i}', 'branch_id': 'B'} for i in range(250)]
    (p1,), _ = await inbox_as_operator(ready, rows, pages=(1,))
    assert p1['rows'] == [] and p1['total'] == 0 and p1['has_more'] is False and p1['scan_incomplete'] is False
    mixed = [{'number': f'M-{i}', 'branch_id': 'A' if i < 5 else 'B'} for i in range(250)]
    (m1, m9), _ = await inbox_as_operator(ready, mixed, pages=(1, 9))
    assert len(m1['rows']) == 5 and m1['total'] == 5
    assert m9['rows'] == [] and m9['total'] == 5 and m9['has_more'] is False
