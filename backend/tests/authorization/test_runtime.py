"""Actual create_app + existing /auth endpoints, on isolated PostgreSQL."""
import pytest
from fastapi import HTTPException
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from tests.authorization.test_foundation import db
from app.authorization.accounts import AccountCredential
from app.authorization.bootstrap import bootstrap_director
from app.authorization.models import AccessState, AccessGroup, Membership, AccessAudit
from app.authorization.shadow import candidate_access, compare, Probe
from app.authorization.evaluator import Resource, Access, Grant
from app.core.config import get_settings
from app.core.security import hash_password
from app.models.user import User
from app.models.auth_audit import AuthAuditEvent
from app.db.session import get_db_session
from app.main import create_app

PW = 'sandbox-runtime-password'

@pytest.fixture
async def runtime(db, monkeypatch):
    monkeypatch.setenv('V3_SETTINGS_ENABLED', 'true')
    monkeypatch.setenv('V3_JWT_SECRET', 'sandbox-runtime-signing-secret-not-for-production')
    monkeypatch.setenv('V3_PASSWORD_PEPPER', 'sandbox-runtime-pepper-not-for-production')
    get_settings.cache_clear()
    async with db.begin() as s:
        await s.run_sync(lambda sync: AccountCredential.__table__.create(sync.connection()))
        await s.run_sync(lambda sync: AuthAuditEvent.__table__.create(sync.connection()))
        from app.models.production.job import ProductionJob
        from app.models.production.schedule import ScheduleAssignment
        await s.run_sync(lambda sync: ProductionJob.__table__.create(sync.connection()))
        await s.run_sync(lambda sync: ScheduleAssignment.__table__.create(sync.connection()))
        from sqlalchemy import text
        await s.execute(text("SELECT setval('settings_foundation_test.users_id_seq',3,true)"))
        for uid in (1, 2, 3):
            (await s.get(User, uid)).password_hash = hash_password(PW)
            s.add(AccountCredential(user_id=uid, generation=1, must_change_password=False))
    app = create_app()
    async def connection():
        async with db() as s: yield s
    app.dependency_overrides[get_db_session] = connection
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        yield db, client

async def login(client, username='test-1', password=PW):
    response = await client.post('/api/v1/auth/login', json={'username':username,'password':password})
    assert response.status_code == 200, response.text
    return {'Authorization':'Bearer '+response.json()['access_token']}, response.json()

async def test_runtime_account_password_api_and_direct_denial(runtime):
    db, client = runtime
    admin, data = await login(client)
    assert data['settings_enabled'] and data['system_director'] and data['workflow_authorization'] == 'legacy'
    assert (await client.get('/api/v1/settings/users', headers=admin)).status_code == 200
    result = await client.post('/api/v1/settings/users', headers=admin, json={'revision':0,'reason':'Sandbox creation','username':'operator-test','display_name':'Operator','password':PW})
    assert result.status_code == 201, result.text
    uid = result.json()['user']['id']
    operator, data = await login(client, 'operator-test')
    assert data['must_change_password']
    assert (await client.get('/api/v1/auth/me', headers=operator)).json()['must_change_password']
    assert (await client.get('/api/v1/production/jobs/tasks', headers=operator)).status_code == 403
    response = await client.post('/api/v1/settings/session/password', headers=operator, json={'current_password':PW,'new_password':PW+'-changed'})
    assert response.status_code == 200, response.text
    assert (await client.get('/api/v1/auth/me', headers=operator)).status_code == 401
    operator, _ = await login(client, 'operator-test', PW+'-changed')
    assert (await client.get('/api/v1/settings/users', headers=operator)).status_code == 403
    assert (await client.get('/api/v1/production/jobs/tasks', headers=operator)).status_code == 403
    result = await client.post(f'/api/v1/settings/users/{uid}/password-reset', headers=admin, json={'revision':2,'reason':'Sandbox reset','password':PW+'-reset'})
    assert result.status_code == 200
    assert (await client.get('/api/v1/auth/me', headers=operator)).status_code == 401
    async with db.begin() as s:
        assert await s.scalar(select(AccessAudit.id).where(AccessAudit.action=='user.password_reset'))

async def test_runtime_revokes_director_membership_on_next_request(runtime):
    _, client = runtime
    first, _ = await login(client)
    second, _ = await login(client,'test-2')
    result = await client.post('/api/v1/settings/users/2/memberships', headers=first, json={'revision':0,'reason':'Revoke sandbox Director','group_id':1,'active':False})
    assert result.status_code == 200
    assert (await client.get('/api/v1/settings/users', headers=second)).status_code == 403
    result = await client.post('/api/v1/settings/users/1/active', headers=first, json={'revision':1,'reason':'Must reject','active':False})
    assert result.status_code == 409

async def test_no_alternate_login_or_password_echo(runtime):
    _, client = runtime
    result = await client.post('/api/v1/settings/session/login', json={'username':'test-1','password':PW})
    assert result.status_code == 404
    value = 'must-not-echo-'*30
    result = await client.post('/api/v1/auth/login', json={'username':'test-1','password':value})
    assert result.status_code == 422 and value not in result.text

async def test_shadow_scope_and_unresolved_mapping_hold_cutover(runtime):
    db, _ = runtime
    async with db.begin() as s:
        user = await s.get(User,3)
        user.permissions = ['production.output.confirm']; user.branch_ids=['A']
        await s.flush()
        candidate = candidate_access(user)
        probes = [Probe('production.output.confirm','output.record',Resource('A',10,3)), Probe('production.output.confirm','output.record',Resource('B',10,3)), Probe('production.output.confirm','output.correct',Resource('A',20,9))]
        report = compare(user,candidate,probes)
        assert report['cutover_allowed']
        scoped = Access(3,True,grants=(Grant(1,'output.record',frozenset({'A'}),'selected',frozenset({10})),))
        restricted = compare(user,scoped,probes)
        assert not restricted['cutover_allowed']  # Scope restriction needs explicit review.
        user.permissions=['production.job.read']
        report = compare(user,candidate_access(user),[Probe('production.job.read','job.read',Resource('A'))])
        assert not report['cutover_allowed'] and report['unresolved_mapping']

async def test_bootstrap_requires_exact_identity_and_is_once_only(runtime):
    db, _ = runtime
    # Reset only this disposable fixture to its pre-bootstrap state.
    from sqlalchemy import delete
    async with db.begin() as s:
        await s.execute(delete(Membership)); await s.execute(delete(AccessGroup));
        (await s.get(AccessState,1)).bootstrapped=False
    async with db.begin() as s:
        with pytest.raises(HTTPException):
            await bootstrap_director(s,owner_user_id=3,expected_username='wrong',approval_reference='Sandbox verified identity')
        assert not (await s.get(AccessState,1)).bootstrapped
    async with db.begin() as s:
        await bootstrap_director(s,owner_user_id=3,expected_username='test-3',approval_reference='Sandbox verified identity')
    async with db.begin() as s:
        with pytest.raises(HTTPException):
            await bootstrap_director(s,owner_user_id=2,expected_username='test-2',approval_reference='No replay')

async def test_assignment_scope_requires_real_id_and_matching_branch(runtime):
    from datetime import date
    from app.models.production.job import ProductionJob
    from app.models.production.schedule import ScheduleAssignment
    db, client = runtime
    async with db.begin() as s:
        job=ProductionJob(accurate_so_number='SCOPE-TEST',branch_id='A')
        s.add(job); await s.flush()
        row=ScheduleAssignment(job_id=job.id,so_line_id='L1',operator_name='Historical label',machine_name='Test',work_date=date(2026,11,15),branch_id='A',qty_planned=1,created_by=1)
        s.add(row); await s.flush(); aid=row.id
    admin, _ = await login(client)
    for ids, branches in [([999],['A']),([aid],['B'])]:
        response=await client.post('/api/v1/settings/groups/2/grants',headers=admin,json={'revision':0,'reason':'Negative scope test','capability':'task.read','ownership':'selected','assignments':ids,'branches':branches})
        assert response.status_code==422
    response=await client.post('/api/v1/settings/groups/2/grants',headers=admin,json={'revision':0,'reason':'Valid ID and branch','capability':'task.read','ownership':'selected','assignments':[aid],'branches':['A']})
    assert response.status_code==201

async def test_failed_runtime_login_keeps_auth_audit(runtime):
    db,client=runtime
    response=await client.post('/api/v1/auth/login',json={'username':'test-1','password':'wrong-test-password'})
    assert response.status_code==401
    async with db.begin() as s:
        log=await s.scalar(select(AuthAuditEvent).where(AuthAuditEvent.result=='failed'))
        assert log is not None

async def test_flag_rollback_cannot_resurrect_legacy_sessions(runtime, monkeypatch):
    from app.core.security import create_access_token
    db, client = runtime
    async with db.begin() as s:
        legacy = create_access_token(await s.get(User,1))
    monkeypatch.setenv('V3_SETTINGS_ENABLED','false'); get_settings.cache_clear()
    response=await client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+legacy})
    assert response.status_code==503
    response=await client.post('/api/v1/auth/login',json={'username':'test-1','password':PW})
    assert response.status_code==503
