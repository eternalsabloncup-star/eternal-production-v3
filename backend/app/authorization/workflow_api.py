"""Sandbox workflow access surfaces. Explicit transactions and fresh DB access."""
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from app.authorization.api import SafeRoute, Mutation, transaction, bearer, result
from app.authorization import accounts, ownership
from app.authorization.evaluator import Resource, evaluate
from app.models.production.job import ProductionJob
from app.models.production.schedule import ScheduleAssignment
from app.services.production.payment_gate import effective_statuses

router = APIRouter(prefix='/production/access', route_class=SafeRoute, tags=['workflow-access'])

async def actor(request: Request, session=Depends(transaction)):
    # Exclusive before any reads on mutations avoids SHARE -> UPDATE deadlocks.
    return await accounts.session_user(session,bearer(request),exclusive=request.method!='GET')

class Assignment(Mutation):
    job_id: int
    user_id: int
    task_kind: Literal['screener','operator','helper','packing','loading','courier']
    assignment_id: int | None = None
    delegated_from_id: int | None = None
    expires_at: datetime | None = None

@router.post('/ownership', status_code=201)
async def assign(body: Assignment, access=Depends(actor), session=Depends(transaction)):
    oid = await ownership.assign(session,actor=access.user_id,**body.model_dump())
    return await result(session,ownership_id=oid)

@router.post('/ownership/{ownership_id}/revoke')
async def revoke(ownership_id:int,body:Mutation,access=Depends(actor),session=Depends(transaction)):
    await ownership.revoke(session,actor=access.user_id,ownership_id=ownership_id,**body.model_dump())
    return await result(session)

async def scoped_rows(session, access, capability):
    """Only identity/schedule/status fields. Never returns receipts or audit payloads."""
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
                          'qty_planned':str(assignment.qty_planned) if assignment else None,
                          'design_status':job.design_status})
    states=await effective_statuses(session,[r['job_id'] for r in items])
    for row in items: row['payment_status']=states[row['job_id']]
    return items

@router.get('/tasks')
async def tasks(access=Depends(actor),session=Depends(transaction)):
    if not access.director and not any(g.capability=='task.read' for g in access.grants):
        raise HTTPException(403,'Task read denied')
    return {'items':await scoped_rows(session,access,'task.read'),'revision':access.revision}

@router.get('/documents/{kind}')
async def document(kind: Literal['job.export','job.print','task.export','report.production.export'],access=Depends(actor),session=Depends(transaction)):
    # Read permission is deliberately neither sufficient nor implicitly imported.
    if not access.director and not any(g.capability==kind for g in access.grants):
        raise HTTPException(403,'Explicit export/print grant required')
    return {'capability':kind,'items':await scoped_rows(session,access,kind),'revision':access.revision}
