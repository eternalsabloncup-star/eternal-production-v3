"""Transactional foundation, not an API or a production cutover.

Call inside ``async with session.begin()`` and discard/rollback on any exception.
No internal commits. Lock order is access-state -> membership/user -> business
resource. All access writers must take the exclusive state lock. Business
integration must hold a shared state lock through its transaction.
Bootstrap/recovery are intentionally unavailable pending verified identity and
approved migration; there is no public system-group creation operation.
"""
from functools import wraps

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.authorization.evaluator import Access, Grant, validate_grant
from app.authorization.models import AccessAudit, AccessGroup, AccessState, Membership, ScopedGrant
from app.models.user import User

def atomic_mutation(function):
    """Rollback the complete mutation even if a caller catches a domain error."""
    @wraps(function)
    async def wrapped(session, **kwargs):
        if not session.in_transaction():
            raise RuntimeError('An explicit outer transaction is required')
        async with session.begin_nested():
            return await function(session, **kwargs)
    return wrapped

async def load_access(session: AsyncSession, user_id: int, *, exclusive: bool = False) -> Access:
    state = await session.scalar(select(AccessState).where(AccessState.id == 1).with_for_update(read=not exclusive).execution_options(populate_existing=True))
    if state is None or not state.bootstrapped:
        raise HTTPException(503, 'Access foundation is not bootstrapped')
    user = await session.get(User, user_id, populate_existing=True)
    if user is None or not user.is_active:
        return Access(user_id, False, revision=state.revision)
    groups = list((await session.scalars(select(AccessGroup).join(Membership, Membership.group_id == AccessGroup.id).where(Membership.user_id == user_id, Membership.active.is_(True), AccessGroup.active.is_(True)).execution_options(populate_existing=True))).all())
    director = any(g.system_key == 'director' for g in groups)
    rows = list((await session.scalars(select(ScopedGrant).where(ScopedGrant.group_id.in_([g.id for g in groups]), ScopedGrant.active.is_(True)).execution_options(populate_existing=True))).all())
    return Access(user_id, True, director, tuple(Grant(r.id, r.capability, frozenset(r.branches), r.ownership, frozenset(r.assignments)) for r in rows), state.revision)

async def _guard(session: AsyncSession, actor: int, revision: int, reason: str) -> AccessState:
    if not reason.strip() or len(reason) > 500:
        raise HTTPException(422, 'A reason of 1-500 characters is required')
    access = await load_access(session, actor, exclusive=True)
    if not access.active or not access.director:
        raise HTTPException(403, 'Director membership required')
    if access.revision != revision:
        raise HTTPException(409, 'Access revision changed; refresh before retrying')
    return await session.get(AccessState, 1)

async def _audit(session, state, actor, action, reason, before, after):
    state.revision += 1
    session.add(AccessAudit(revision=state.revision, actor_user_id=actor, action=action, reason=reason.strip(), before=before, after=after))
    await session.flush()

async def _last_admin(session):
    await session.flush()
    count = await session.scalar(select(func.count()).select_from(Membership).join(User, User.id == Membership.user_id).join(AccessGroup, AccessGroup.id == Membership.group_id).where(User.is_active.is_(True), Membership.active.is_(True), AccessGroup.active.is_(True), AccessGroup.system_key == 'director'))
    if not count:
        raise HTTPException(409, 'Cannot remove the last active Director')

@atomic_mutation
async def create_group(session, *, actor: int, revision: int, reason: str, name: str) -> int:
    state = await _guard(session, actor, revision, reason)
    if not name.strip() or len(name.strip()) > 120:
        raise HTTPException(422, 'Invalid group name')
    group = AccessGroup(name=name.strip(), system_key=None)
    session.add(group)
    await session.flush()
    await _audit(session, state, actor, 'group.create', reason, {}, {'group_id': group.id, 'name': group.name})
    return group.id

@atomic_mutation
async def set_membership(session, *, actor: int, revision: int, reason: str, user_id: int, group_id: int, active: bool):
    state = await _guard(session, actor, revision, reason)
    user = await session.get(User, user_id, populate_existing=True)
    group = await session.get(AccessGroup, group_id, populate_existing=True)
    if user is None or group is None or not group.active:
        raise HTTPException(422, 'Unknown user or inactive group')
    membership = await session.get(Membership, (user_id, group_id), populate_existing=True)
    before = {'user_id': user_id, 'group_id': group_id, 'active': bool(membership and membership.active)}
    if membership is None:
        membership = Membership(user_id=user_id, group_id=group_id, active=active)
        session.add(membership)
    else:
        membership.active = active
    await _last_admin(session)
    await _audit(session, state, actor, 'membership.set', reason, before, {**before, 'active': active})

@atomic_mutation
async def set_user_active(session, *, actor: int, revision: int, reason: str, user_id: int, active: bool):
    state = await _guard(session, actor, revision, reason)
    user = await session.get(User, user_id, populate_existing=True)
    if user is None:
        raise HTTPException(404, 'User not found')
    before = {'user_id': user_id, 'active': user.is_active}
    user.is_active = active
    await _last_admin(session)
    await _audit(session, state, actor, 'user.active', reason, before, {'user_id': user_id, 'active': active})

@atomic_mutation
async def add_grant(session, *, actor: int, revision: int, reason: str, group_id: int, grant: Grant) -> int:
    state = await _guard(session, actor, revision, reason)
    try:
        validate_grant(grant)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    group = await session.get(AccessGroup, group_id, populate_existing=True)
    if group is None or not group.active or group.system_key is not None:
        raise HTTPException(422, 'Grants require an active ordinary group')
    row = ScopedGrant(group_id=group_id, capability=grant.capability, branches=sorted(grant.branches), ownership=grant.ownership, assignments=sorted(grant.assignments))
    session.add(row)
    await session.flush()
    await _audit(session, state, actor, 'grant.create', reason, {}, {'grant_id': row.id, 'group_id': group_id, 'capability': row.capability, 'branches': row.branches, 'ownership': row.ownership, 'assignments': row.assignments})
    return row.id

@atomic_mutation
async def revoke_grant(session, *, actor: int, revision: int, reason: str, grant_id: int):
    state = await _guard(session, actor, revision, reason)
    row = await session.get(ScopedGrant, grant_id, populate_existing=True)
    if row is None:
        raise HTTPException(404, 'Grant not found')
    before = {'grant_id': row.id, 'active': row.active}
    row.active = False
    await _audit(session, state, actor, 'grant.revoke', reason, before, {'grant_id': row.id, 'active': False})
