"""Settings API, registered only when V3_SETTINGS_ENABLED is explicitly enabled."""
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, StrictInt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.session import get_db_session
from app.models.user import User
from app.authorization import accounts, service
from app.authorization.catalog import CATALOG
from app.authorization.evaluator import Grant
from app.authorization.models import AccessState, AccessGroup, AccessAudit, Membership, ScopedGrant

class SafeRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request):
            try:
                return await original(request)
            except RequestValidationError:
                # Never echo input bodies: validation errors can contain passwords.
                return JSONResponse(status_code=422, content={'detail': 'Invalid request fields'})
            except IntegrityError:
                return JSONResponse(status_code=409, content={'detail': 'Record conflicts with existing data'})
        return handler

router = APIRouter(prefix='/settings', tags=['settings-isolated'], route_class=SafeRoute)

class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Mutation(StrictBody):
    revision: StrictInt = Field(ge=0)
    reason: str = Field(min_length=1, max_length=500)

class Login(StrictBody):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(max_length=200)

class PasswordChange(StrictBody):
    current_password: SecretStr = Field(max_length=200)
    new_password: SecretStr = Field(max_length=200)

class Profile(Mutation):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=120)

class CreateUser(Profile):
    password: SecretStr = Field(max_length=200)

class ResetPassword(Mutation):
    password: SecretStr | None = Field(default=None, max_length=200)

class Active(Mutation):
    active: StrictBool

class GroupBody(Mutation):
    name: str = Field(min_length=1, max_length=120)

class MemberBody(Active):
    group_id: StrictInt = Field(gt=0)

class GrantBody(Mutation):
    capability: str = Field(max_length=120)
    branches: list[str] = Field(default_factory=list, max_length=100)
    ownership: Literal['all', 'own', 'selected'] = 'all'
    assignments: list[StrictInt] = Field(default_factory=list, max_length=500)


def bearer(request):
    scheme, _, value = request.headers.get('authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not value:
        raise HTTPException(401, 'Authentication required')
    return value

async def transaction(session=Depends(get_db_session)):
    async with session.begin():
        yield session

async def director(request: Request, session=Depends(transaction)):
    access = await accounts.session_user(session, bearer(request), exclusive=request.method != 'GET')
    if not access.director:
        raise HTTPException(403, 'Director membership required')
    return access

async def result(session, **extra):
    return {'revision': (await session.get(AccessState, 1)).revision, **extra}

def mutation(body, access):
    return {'actor': access.user_id, 'revision': body.revision, 'reason': body.reason}

@router.post('/session/login')
async def login(body: Login, session=Depends(transaction)):
    from app.core.config import get_settings
    if get_settings().v3_settings_enabled:
        raise HTTPException(404, "Use /auth/login")
    return await accounts.authenticate(session, body.username, body.password.get_secret_value())

@router.post('/session/password')
async def password_change(body: PasswordChange, request: Request, session=Depends(transaction)):
    return await accounts.change_password(session, token=bearer(request), current_password=body.current_password.get_secret_value(), new_password=body.new_password.get_secret_value())

@router.get('/capabilities')
async def capabilities(access=Depends(director)):
    return {'revision': access.revision, 'items': [asdict(c) for c in CATALOG.values()]}

@router.get('/users')
async def users(q: str = Query('', max_length=64), offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), access=Depends(director), session=Depends(transaction)):
    rows = await session.scalars(select(User).where(User.username.contains(q, autoescape=True)).order_by(User.id).offset(offset).limit(limit))
    return await result(session, items=[accounts.profile(u) for u in rows])

@router.post('/users', status_code=201)
async def create_user(body: CreateUser, access=Depends(director), session=Depends(transaction)):
    user = await accounts.create_user(session, **mutation(body, access), username=body.username, display_name=body.display_name, password=body.password.get_secret_value())
    return await result(session, user=user)

@router.patch('/users/{user_id}')
async def profile(user_id: int, body: Profile, access=Depends(director), session=Depends(transaction)):
    user = await accounts.update_profile(session, **mutation(body, access), user_id=user_id, username=body.username, display_name=body.display_name)
    return await result(session, user=user)

@router.post('/users/{user_id}/active')
async def active(user_id: int, body: Active, access=Depends(director), session=Depends(transaction)):
    await accounts.set_active(session, **mutation(body, access), user_id=user_id, active=body.active)
    return await result(session)

@router.post('/users/{user_id}/password-reset')
async def reset(user_id: int, body: ResetPassword, access=Depends(director), session=Depends(transaction)):
    await accounts.reset_password(session, **mutation(body, access), user_id=user_id, password=body.password.get_secret_value() if body.password else None)
    return await result(session)

@router.get('/groups')
async def groups(access=Depends(director), session=Depends(transaction)):
    rows = await session.scalars(select(AccessGroup).order_by(AccessGroup.id))
    return await result(session, items=[{'id': g.id, 'name': g.name, 'system': g.system_key is not None, 'active': g.active} for g in rows])

@router.post('/groups', status_code=201)
async def create_group(body: GroupBody, access=Depends(director), session=Depends(transaction)):
    gid = await service.create_group(session, **mutation(body, access), name=body.name)
    return await result(session, group_id=gid)

@router.post('/users/{user_id}/memberships')
async def membership(user_id: int, body: MemberBody, access=Depends(director), session=Depends(transaction)):
    await service.set_membership(session, **mutation(body, access), user_id=user_id, group_id=body.group_id, active=body.active)
    return await result(session)

@router.get('/groups/{group_id}/grants')
async def grants(group_id: int, access=Depends(director), session=Depends(transaction)):
    rows = await session.scalars(select(ScopedGrant).where(ScopedGrant.group_id == group_id).order_by(ScopedGrant.id))
    return await result(session, items=[{'id': g.id, 'capability': g.capability, 'branches': g.branches, 'ownership': g.ownership, 'assignments': g.assignments, 'active': g.active} for g in rows])

@router.post('/groups/{group_id}/grants', status_code=201)
async def add_grant(group_id: int, body: GrantBody, access=Depends(director), session=Depends(transaction)):
    if body.ownership == 'selected':
        from app.models.production.schedule import ScheduleAssignment
        rows = list((await session.scalars(select(ScheduleAssignment).where(ScheduleAssignment.id.in_(body.assignments)))).all())
        if len(rows) != len(set(body.assignments)) or any(row.branch_id not in body.branches for row in rows):
            raise HTTPException(422, 'Assignments must exist within the granted branches')
    grant = Grant(0, body.capability, frozenset(body.branches), body.ownership, frozenset(body.assignments))
    gid = await service.add_grant(session, **mutation(body, access), group_id=group_id, grant=grant)
    return await result(session, grant_id=gid)

@router.post('/grants/{grant_id}/revoke')
async def revoke(grant_id: int, body: Mutation, access=Depends(director), session=Depends(transaction)):
    await service.revoke_grant(session, **mutation(body, access), grant_id=grant_id)
    return await result(session)

@router.get('/users/{user_id}/effective-access')
async def effective(user_id: int, access=Depends(director), session=Depends(transaction)):
    target = await service.load_access(session, user_id)
    if await session.get(User, user_id) is None:
        raise HTTPException(404, 'User not found')
    members = await session.scalars(select(Membership.group_id).where(Membership.user_id == user_id, Membership.active.is_(True)))
    return {'revision': target.revision, 'user_id': target.user_id, 'active': target.active, 'director': target.director,
            'memberships': list(members), 'grants': [{'id': g.id, 'capability': g.capability, 'branches': sorted(g.branches), 'ownership': g.ownership, 'assignments': sorted(g.assignments)} for g in target.grants]}

@router.get('/access-audit')
async def audit(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), access=Depends(director), session=Depends(transaction)):
    rows = await session.scalars(select(AccessAudit).order_by(AccessAudit.id.desc()).offset(offset).limit(limit))
    return await result(session, items=[{'id': a.id, 'revision': a.revision, 'actor_user_id': a.actor_user_id, 'action': a.action, 'reason': a.reason, 'before': a.before, 'after': a.after, 'created_at': a.created_at} for a in rows])
