"""Real request guards on isolated PostgreSQL; no Live endpoints."""
import pytest
from datetime import date
from httpx import AsyncClient, ASGITransport
from app.db.base import Base
from app.db.session import get_db_session
from app.core.config import get_settings
from app.main import create_app
from app.models.production.job import ProductionJob
from app.models.production.schedule import ScheduleAssignment
from app.authorization.models import ScopedGrant, Membership
from app.authorization.ownership import TaskOwnership
from app.authorization.workflow_map import WORKFLOW, INBOX, PAYROLL
from app.authorization.catalog import CATALOG
from tests.authorization.test_foundation import db
from tests.authorization.test_runtime import runtime, login

@pytest.fixture
async def enforced(runtime, monkeypatch):
    factory,_=runtime
    monkeypatch.setenv('V3_WORKFLOW_AUTHORIZATION','enforced');get_settings.cache_clear()
    async with factory.begin() as s:
        await s.run_sync(lambda sync:Base.metadata.create_all(sync.connection()))
        for i,branch in [(1,'A'),(2,'B')]: s.add(ProductionJob(id=i,accurate_so_number=f'ACCESS-{i}',branch_id=branch))
        await s.flush()
        for i,job in [(1,1),(2,1),(3,2)]:
            s.add(ScheduleAssignment(id=i,job_id=job,branch_id='A' if job==1 else 'B',so_line_id=str(i),operator_name='Historical name',machine_name='Test',work_date=date(2026,11,13),qty_planned=10,created_by=1))
    app=create_app()
    async def connection():
        async with factory() as s: yield s
    app.dependency_overrides[get_db_session]=connection
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as c: yield factory,c

def test_manifest_covers_actual_routes():
    from app.api.production.workflow import router as w
    from app.api.production_inbox import router as i
    from app.api.production.payroll import router as p
    from app.api.production.operations import router as o
    for routers,mapping in [((w,o),WORKFLOW),((i,),INBOX),((p,),PAYROLL)]:
        assert {r.endpoint.__name__ for router in routers for r in router.routes}==set(mapping)
        assert all(cap in CATALOG for cap,_ in mapping.values())

async def grant(db,cap,ownership='all'):
    async with db.begin() as s:
        g=ScopedGrant(group_id=2,capability=cap,branches=['A'],ownership=ownership,assignments=[],active=True)
        s.add(g); await s.flush(); return g.id

async def test_director_cross_branch_no_legacy_or_and_revocation(enforced):
    db,c=enforced
    director,_=await login(c);operator,_=await login(c,'test-3')
    for job in (1,2):
        r=await c.get(f'/api/v1/production/jobs/{job}',headers=director)
        assert r.status_code==200,r.text
    from app.models.user import User
    async with db.begin() as s:
        u=await s.get(User,3);u.permissions=['production.job.read'];u.branch_ids=['A','B']
    assert (await c.get('/api/v1/production/jobs/1',headers=operator)).status_code==403
    gid=await grant(db,'job.read')
    assert (await c.get('/api/v1/production/jobs/1',headers=operator)).status_code==200
    assert (await c.get('/api/v1/production/jobs/2',headers=operator)).status_code==403
    async with db.begin() as s: (await s.get(ScopedGrant,gid)).active=False
    assert (await c.get('/api/v1/production/jobs/1',headers=operator)).status_code==403

async def test_ownership_export_revocation_and_history(enforced):
    db,c=enforced
    director,_=await login(c);operator,_=await login(c,'test-3')
    await grant(db,'task.read','own')
    assert (await c.get('/api/v1/production/access/tasks',headers=operator)).json()['items']==[]
    body={'revision':0,'reason':'Explicit task assignment','job_id':1,'user_id':3,'task_kind':'operator','assignment_id':1}
    assert (await c.post('/api/v1/production/access/ownership',headers=operator,json=body)).status_code==403
    r=await c.post('/api/v1/production/access/ownership',headers=director,json=body)
    assert r.status_code==201,r.text
    oid=r.json()['ownership_id']
    rows=(await c.get('/api/v1/production/access/tasks',headers=operator)).json()['items']
    assert [(r['job_id'],r['assignment_id']) for r in rows]==[(1,1)]
    url='/api/v1/production/access/documents/task.export'
    assert (await c.get(url,headers=operator)).status_code==403
    await grant(db,'task.export','own')
    assert len((await c.get(url,headers=operator)).json()['items'])==1
    assert (await c.get('/api/v1/production/access/documents/job.print',headers=operator)).status_code==403
    assert (await c.get('/api/v1/production/access/documents/job.print',headers=director)).status_code==200
    r=await c.post(f'/api/v1/production/access/ownership/{oid}/revoke',headers=director,json={'revision':1,'reason':'Revoke task access'})
    assert r.status_code==200,r.text
    assert (await c.get(url,headers=operator)).json()['items']==[]
    async with db() as s:
        assert (await s.get(ScheduleAssignment,1)).operator_name=='Historical name'
        assert (await s.get(TaskOwnership,oid)).active is False

async def test_manager_no_input_and_cross_job_rejected(enforced):
    db,c=enforced
    director,_=await login(c);operator,_=await login(c,'test-3')
    await grant(db,'assignment.ownership.manage')
    body={'revision':0,'reason':'Wrong job','job_id':1,'user_id':3,'task_kind':'helper','assignment_id':3}
    assert (await c.post('/api/v1/production/access/ownership',headers=operator,json=body)).status_code==422
    assert (await c.post('/api/v1/production/jobs/1/payment/bypass',headers=operator,json={'reason':'No payment permission'})).status_code==403
    assert (await c.post('/api/v1/production/jobs/tasks',headers=operator,json={'sync_ensure':True,'jobs':[]})).status_code==403

@pytest.mark.parametrize('kind',['screener','operator','helper','packing','loading','courier'])
async def test_stable_identity_all_roles_and_delegation_revocation(enforced,kind):
    db,c=enforced
    director,_=await login(c)
    body={'revision':0,'reason':'Stable ID ownership','job_id':1,'user_id':3,'task_kind':kind,'assignment_id':1}
    r=await c.post('/api/v1/production/access/ownership',headers=director,json=body)
    assert r.status_code==201,r.text
    oid=r.json()['ownership_id']
    r=await c.post('/api/v1/production/access/ownership',headers=director,json={**body,'revision':1,'user_id':2,'delegated_from_id':oid})
    assert r.status_code==201,r.text
    from app.authorization.ownership import owned
    async with db() as s: assert await owned(s,2,1,kind,1)
    r=await c.post(f'/api/v1/production/access/ownership/{oid}/revoke',headers=director,json={'revision':2,'reason':'End parent assignment'})
    assert r.status_code==200
    async with db() as s: assert await owned(s,2,1,kind,1) is None

async def test_shadow_actual_grants_records_intentional_narrowing(enforced):
    db,_=enforced
    from app.models.user import User
    from app.authorization.service import load_access
    from app.authorization.shadow import compare,Probe
    from app.authorization.evaluator import Resource
    await grant(db,'output.record','own')
    async with db.begin() as s:
        u=await s.get(User,3);u.permissions=['production.output.confirm'];u.branch_ids=['A'];await s.flush()
        access=await load_access(s,3)
        report=compare(u,access,[Probe('production.output.confirm','output.record',Resource('A',1,3)),Probe('production.output.confirm','output.record',Resource('A',2,2)),Probe('production.output.confirm','output.record',Resource('B',1,3))])
        assert [(r['legacy'],r['candidate']) for r in report['comparisons']]==[(True,True),(True,False),(False,False)]
        assert not report['cutover_allowed']  # Narrowing requires explicit inventory review.

async def test_payment_design_validation_not_bypassed_by_director(enforced):
    _,c=enforced
    director,_=await login(c)
    r=await c.post('/api/v1/production/jobs/1/schedule/assignments',headers=director,json={'so_line_id':'1','operator_name':'Historical name','machine_name':'Test','work_date':'2026-11-13','qty_planned':1})
    assert r.status_code==409,r.text

async def test_every_legacy_endpoint_denies_empty_settings_grants(enforced):
    _,c=enforced
    operator,_=await login(c,'test-3')
    from app.api.production.workflow import router as w
    from app.api.production_inbox import router as i
    from app.api.production.payroll import router as p
    from app.api.production.operations import router as o
    import re
    count=0
    for router in (w,i,p,o):
        for route in router.routes:
            path=re.sub(r'\{[^}]+\}','1','/api/v1'+route.path)
            r=await c.request(next(iter(route.methods)),path,headers=operator,json={})
            assert r.status_code==403,(path,r.status_code,r.text)
            count+=1
    assert count==62

async def test_ownership_concurrent_revision_and_atomic_audit(enforced,monkeypatch):
    import asyncio
    from sqlalchemy import select,func
    from app.authorization import ownership
    db,c=enforced
    director,_=await login(c)
    body={'revision':0,'reason':'Concurrent ownership test','job_id':1,'user_id':3,'task_kind':'operator','assignment_id':1}
    responses=await asyncio.gather(*(c.post('/api/v1/production/access/ownership',headers=director,json=body) for _ in range(2)))
    assert sorted(r.status_code for r in responses)==[201,409]
    async def audit_failure(*a,**kw): raise RuntimeError('Synthetic audit failure')
    monkeypatch.setattr(ownership,'_audit',audit_failure)
    with pytest.raises(RuntimeError,match='Synthetic audit failure'):
        async with db.begin() as s:
            await ownership.assign(s,actor=1,revision=1,reason='Atomic rollback',job_id=1,user_id=3,task_kind='helper',assignment_id=1)
    async with db() as s: assert await s.scalar(select(func.count()).select_from(TaskOwnership))==1

async def test_board_sensitive_fields_require_separate_manual_grants(enforced):
    from app.models.production.payment import PaymentBypass
    db,c=enforced
    operator,_=await login(c,'test-3')
    await grant(db,'job.board.read')
    async with db.begin() as s: s.add(PaymentBypass(job_id=1,reason='Sensitive approval reason',authorized_by=1,active=True))
    r=await c.get('/api/v1/production/jobs/1/board',headers=operator)
    assert r.status_code==200,r.text
    assert r.json()['payment_bypasses']==[]
    await grant(db,'payment.evidence.read')
    r=await c.get('/api/v1/production/jobs/1/board',headers=operator)
    assert len(r.json()['payment_bypasses'])==1
