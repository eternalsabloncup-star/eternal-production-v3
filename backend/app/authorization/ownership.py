"""Stable user ownership/delegation, independent of historical operator labels."""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Integer, CheckConstraint, func, select
from sqlalchemy.orm import Mapped, mapped_column
from fastapi import HTTPException
from app.db.base import Base
from app.models.user import User
from app.models.production.job import ProductionJob
from app.models.production.schedule import ScheduleAssignment
from app.authorization.models import AccessState
from app.authorization.service import load_access, atomic_mutation, _audit
from app.authorization.evaluator import evaluate, Resource

KINDS = {'screener','operator','helper','packing','loading','courier'}

class TaskOwnership(Base):
    __tablename__ = 'task_ownerships'
    __table_args__ = (CheckConstraint("task_kind IN ('screener','operator','helper','packing','loading','courier')",name='ck_task_ownership_kind'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('production_jobs.id', ondelete='RESTRICT'), index=True)
    assignment_id: Mapped[int | None] = mapped_column(ForeignKey('schedule_assignments.id', ondelete='RESTRICT'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    task_kind: Mapped[str] = mapped_column(String(24))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    delegated_from_id: Mapped[int | None] = mapped_column(ForeignKey('task_ownerships.id', ondelete='RESTRICT'))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now())

async def owned(session, user_id, job_id, kind, assignment_id=None):
    rows = (await session.scalars(select(TaskOwnership).where(TaskOwnership.user_id==user_id, TaskOwnership.job_id==job_id,
        TaskOwnership.task_kind==kind, TaskOwnership.active.is_(True),
        (TaskOwnership.expires_at.is_(None) | (TaskOwnership.expires_at>func.now()))))).all()
    for row in rows:
        if row.assignment_id != assignment_id:
            continue
        if row.delegated_from_id:
            parent = await session.get(TaskOwnership,row.delegated_from_id,populate_existing=True)
            if parent is None or not parent.active or parent.delegated_from_id:
                continue
            if parent.expires_at is not None:
                from datetime import timezone
                if parent.expires_at <= datetime.now(timezone.utc): continue
        return row.id
    return None

@atomic_mutation
async def assign(session, *, actor, revision, reason, job_id, user_id, task_kind, assignment_id=None, delegated_from_id=None, expires_at=None):
    access=await load_access(session,actor,exclusive=True)
    if access.revision!=revision: raise HTTPException(409,'Access revision changed')
    if not reason.strip() or len(reason)>500 or task_kind not in KINDS: raise HTTPException(422,'Valid reason/task kind required')
    job=await session.get(ProductionJob,job_id)
    if job is None: raise HTTPException(404,'Job not found')
    if assignment_id is not None:
        a=await session.get(ScheduleAssignment,assignment_id)
        if a is None or a.job_id!=job_id: raise HTTPException(422,'Assignment belongs to another job')
    capability='assignment.delegation.manage' if delegated_from_id else 'assignment.ownership.manage'
    # Management scope is independently granted; it does not authorize input.
    if not evaluate(access,capability,Resource(job.branch_id,assignment_id)).allowed: raise HTTPException(403,'Task management scope denied')
    target=await session.get(User,user_id)
    if target is None or not target.is_active: raise HTTPException(422,'Active target user required')
    if expires_at is not None:
        from datetime import timezone
        if expires_at.tzinfo is None or expires_at<=datetime.now(timezone.utc): raise HTTPException(422,'Future timezone-aware expiry required')
    if delegated_from_id:
        parent=await session.get(TaskOwnership,delegated_from_id,populate_existing=True)
        if parent is None or not parent.active or parent.delegated_from_id or (parent.job_id,parent.assignment_id,parent.task_kind)!=(job_id,assignment_id,task_kind): raise HTTPException(422,'Invalid delegation source')
        if parent.expires_at and (expires_at is None or expires_at>parent.expires_at): raise HTTPException(422,'Delegation exceeds source expiry')
    row=TaskOwnership(job_id=job_id,user_id=user_id,task_kind=task_kind,assignment_id=assignment_id,created_by=actor,delegated_from_id=delegated_from_id,expires_at=expires_at)
    session.add(row); await session.flush()
    await _audit(session,await session.get(AccessState,1),actor,'assignment.delegate' if delegated_from_id else 'assignment.assign',reason,{}, {'ownership_id':row.id,'job_id':job_id,'assignment_id':assignment_id,'user_id':user_id,'task_kind':task_kind,'delegated_from_id':delegated_from_id})
    return row.id

@atomic_mutation
async def revoke(session, *, actor, revision, reason, ownership_id):
    access=await load_access(session,actor,exclusive=True)
    if access.revision!=revision: raise HTTPException(409,'Access revision changed')
    if not reason.strip() or len(reason)>500: raise HTTPException(422,'Reason required')
    row=await session.get(TaskOwnership,ownership_id,populate_existing=True)
    if row is None: raise HTTPException(404,'Ownership not found')
    job=await session.get(ProductionJob,row.job_id)
    cap='assignment.delegation.manage' if row.delegated_from_id else 'assignment.ownership.manage'
    if not evaluate(access,cap,Resource(job.branch_id,row.assignment_id)).allowed: raise HTTPException(403,'Task management scope denied')
    before={'ownership_id':row.id,'active':row.active}; row.active=False
    await _audit(session,await session.get(AccessState,1),actor,'assignment.revoke',reason,before,{'ownership_id':row.id,'active':False})
