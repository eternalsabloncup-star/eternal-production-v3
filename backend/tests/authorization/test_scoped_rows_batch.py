"""scoped_rows batching: identical dataset to the previous per-job implementation, fewer queries."""
from datetime import date
from sqlalchemy import select, event
from app.authorization import workflow_api, ownership
from app.authorization.evaluator import Resource, evaluate
from app.authorization.service import load_access
from app.models.production.job import ProductionJob
from app.models.production.schedule import ScheduleAssignment
from app.services.production.payment_gate import effective_statuses
from tests.authorization.test_foundation import db
from tests.authorization.test_runtime import runtime
from tests.authorization.test_workflow_access import enforced
from tests.authorization.test_workflow_completion import ready, grant


async def reference_scoped_rows(session, access, capability):
    """Verbatim pre-batching algorithm (per-job queries) kept as the oracle."""
    jobs=(await session.scalars(select(ProductionJob).order_by(ProductionJob.id))).all()
    items=[]
    for job in jobs:
        assignments=(await session.scalars(select(ScheduleAssignment).where(ScheduleAssignment.job_id==job.id))).all()
        bindings=(await session.scalars(select(ownership.TaskOwnership).where(ownership.TaskOwnership.job_id==job.id,ownership.TaskOwnership.user_id==access.user_id,ownership.TaskOwnership.active.is_(True)))).all()
        resources={}
        for binding in bindings:
            oid=await ownership.owned(session,access.user_id,job.id,binding.task_kind,binding.assignment_id)
            if oid: resources[binding.assignment_id]=Resource(job.branch_id,binding.assignment_id,access.user_id,oid)
        candidates=list(assignments)
        if not candidates or None in resources: candidates.append(None)
        for assignment in candidates:
            aid=assignment.id if assignment else None
            resource=resources.get(aid,Resource(job.branch_id,aid))
            if not evaluate(access,capability,resource).allowed: continue
            items.append({'job_id':job.id,'assignment_id':aid,'branch_id':job.branch_id,'so_number':job.accurate_so_number,
                          'qty_planned':str(assignment.qty_planned) if assignment else None,'design_status':job.design_status})
    states=await effective_statuses(session,[r['job_id'] for r in items])
    for row in items: row['payment_status']=states[row['job_id']]
    return items


def counted(session):
    box=[0]
    engine=session.bind.sync_engine if hasattr(session.bind,'sync_engine') else session.bind
    def hook(*a): box[0]+=1
    event.listen(engine,'before_cursor_execute',hook)
    return box,lambda: event.remove(engine,'before_cursor_execute',hook)


async def test_batched_rows_identical_and_fewer_queries(ready):
    db,_=ready
    async with db.begin() as s:
        for j in range(10,40):
            s.add(ProductionJob(id=j,accurate_so_number=f'BATCH-{j}',branch_id='A' if j%3 else 'B'))
        await s.flush()
        for j in range(10,40):
            for k in range(3):
                s.add(ScheduleAssignment(job_id=j,branch_id='A' if j%3 else 'B',so_line_id=str(k),operator_name='x',machine_name='m',work_date=date(2026,11,13),qty_planned=5+k,created_by=1))
    async with db.begin() as s:
        await s.flush()
    async with db() as s:
        first={j:(await s.scalar(select(ScheduleAssignment.id).where(ScheduleAssignment.job_id==j).order_by(ScheduleAssignment.id))) for j in (11,13,16)}
    from app.authorization.ownership import TaskOwnership
    async with db.begin() as s:
        for job,kind in [(11,'operator'),(13,'operator'),(16,'helper')]:
            s.add(TaskOwnership(job_id=job,user_id=3,task_kind=kind,assignment_id=first[job],active=True,created_by=1))
    await grant(db,'task.read',ownership='own'); await grant(db,'job.print')
    results={}
    for cap in ('task.read','job.print'):
        async with db() as s:
            access=await load_access(s,3)
            box,off=counted(s); old=await reference_scoped_rows(s,access,cap); old_n=box[0]; off()
            await s.rollback()
            box,off=counted(s); new=await workflow_api.scoped_rows(s,access,cap); new_n=box[0]; off()
        key=lambda r:(r['job_id'],r['assignment_id'] or 0)
        assert sorted(old,key=key)==sorted(new,key=key) and new
        assert new_n<old_n/5
        results[cap]=(len(new),old_n,new_n)
    own,wide=results['task.read'],results['job.print']
    assert own[0]==3 and wide[0]>3  # ownership narrows; 'all' widens only inside branch A
    async with db() as s:
        director=await load_access(s,1)
        assert {r['branch_id'] for r in await workflow_api.scoped_rows(s,director,'job.print')}>={'A','B'}
    print('QUERY_COUNTS(rows,old,new)',results)
