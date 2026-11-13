"""Account lifecycle using existing V3 password/JWT primitives.

Managed runtime is explicitly enabled; isolated tests retain a separate audience.
Credential generation is checked on every managed authenticated request.
"""
from datetime import UTC, datetime, timedelta
import re

import jwt
from fastapi import HTTPException
from sqlalchemy import CheckConstraint, ForeignKey, Integer, Boolean, select
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import User
from app.core.config import get_settings
from app.core.security import hash_password, verify_password, require_jwt_secret
from app.authorization.models import AccessState
from app.authorization.service import atomic_mutation, _guard, _audit, load_access

AUDIENCE = 'settings-foundation-isolated'

def session_audience():
    return 'eternal-v3-managed' if get_settings().v3_settings_enabled else AUDIENCE

class AccountCredential(Base):
    __tablename__ = 'access_account_credentials'
    __table_args__ = (CheckConstraint('generation >= 1', name='ck_account_generation'),)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)


def profile(user):
    return {'id': user.id, 'username': user.username, 'display_name': user.display_name, 'is_active': user.is_active}


def validate_profile(username, display_name):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', username) or not display_name.strip() or len(display_name) > 120:
        raise HTTPException(422, 'Invalid username or display name')


def validate_password(password):
    if not 12 <= len(password) <= 200:
        raise HTTPException(422, 'Password must contain 12-200 characters')


@atomic_mutation
async def create_user(session, *, actor, revision, reason, username, display_name, password):
    state = await _guard(session, actor, revision, reason)
    validate_profile(username, display_name)
    validate_password(password)
    user = User(username=username, display_name=display_name.strip(), password_hash=hash_password(password),
                permissions=[], branch_ids=[], is_active=True)
    session.add(user)
    await session.flush()
    session.add(AccountCredential(user_id=user.id, generation=1, must_change_password=True))
    await _audit(session, state, actor, 'user.create', reason, {}, {**profile(user), 'must_change_password': True})
    return profile(user)


@atomic_mutation
async def update_profile(session, *, actor, revision, reason, user_id, username, display_name):
    state = await _guard(session, actor, revision, reason)
    validate_profile(username, display_name)
    user = await session.get(User, user_id, populate_existing=True)
    if user is None:
        raise HTTPException(404, 'User not found')
    before = profile(user)
    if user.username != username:
        credential = await session.get(AccountCredential, user_id, populate_existing=True)
        if credential is None:
            raise HTTPException(409, 'Account credential migration required')
        credential.generation += 1
    user.username, user.display_name = username, display_name.strip()
    await _audit(session, state, actor, 'user.profile', reason, before, profile(user))
    return profile(user)


@atomic_mutation
async def reset_password(session, *, actor, revision, reason, user_id, password=None):
    """None forces change and revokes sessions without replacing the password."""
    state = await _guard(session, actor, revision, reason)
    user = await session.get(User, user_id, populate_existing=True)
    credential = await session.get(AccountCredential, user_id, populate_existing=True)
    if user is None or credential is None:
        raise HTTPException(409, 'Account credential migration required')
    before = {'user_id': user_id, 'generation': credential.generation, 'must_change_password': credential.must_change_password}
    if password is not None:
        validate_password(password)
        if verify_password(password, user.password_hash):
            raise HTTPException(422, 'New password must differ from current password')
        user.password_hash = hash_password(password)
    credential.generation += 1
    credential.must_change_password = True
    await _audit(session, state, actor, 'user.password_reset' if password is not None else 'user.force_password_change', reason,
                 before, {'user_id': user_id, 'generation': credential.generation, 'must_change_password': True})


def token_for(user, credential):
    cfg = get_settings()
    now = datetime.now(UTC)
    return jwt.encode({'sub': str(user.id), 'cv': credential.generation, 'iss': 'eternal-production-v3',
                       'aud': session_audience(), 'iat': now, 'exp': now + timedelta(hours=cfg.v3_jwt_hours)},
                      require_jwt_secret(cfg), algorithm='HS256')


async def authenticate(session, username, password):
    # Shared state lock is acquired before reading credentials, consistent with writers.
    state = await session.scalar(select(AccessState).where(AccessState.id == 1).with_for_update(read=True))
    if state is None or not state.bootstrapped:
        raise HTTPException(503, 'Access foundation is not bootstrapped')
    user = await session.scalar(select(User).where(User.username == username).execution_options(populate_existing=True))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise HTTPException(401, 'Invalid credentials')
    credential = await session.get(AccountCredential, user.id, populate_existing=True)
    if credential is None:
        raise HTTPException(403, 'Account credential migration required')
    return {'access_token': token_for(user, credential), 'must_change_password': credential.must_change_password}


async def session_user(session, token, *, allow_password_change=False, exclusive=False):
    try:
        payload = jwt.decode(token, require_jwt_secret(), algorithms=['HS256'], audience=session_audience(),
                             issuer='eternal-production-v3', options={'require': ['sub', 'cv', 'exp', 'iat', 'aud']})
        user_id = int(payload['sub'])
        if type(payload['cv']) is not int:
            raise ValueError('Invalid version')
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(401, 'Invalid session') from exc
    access = await load_access(session, user_id, exclusive=exclusive)
    credential = await session.get(AccountCredential, user_id, populate_existing=True)
    if not access.active or credential is None or credential.generation != payload['cv']:
        raise HTTPException(401, 'Session revoked')
    if credential.must_change_password and not allow_password_change:
        raise HTTPException(403, 'Password change required')
    return access


@atomic_mutation
async def change_password(session, *, token, current_password, new_password):
    access = await session_user(session, token, allow_password_change=True, exclusive=True)
    user = await session.get(User, access.user_id, populate_existing=True)
    credential = await session.get(AccountCredential, access.user_id, populate_existing=True)
    validate_password(new_password)
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(401, 'Invalid credentials')
    if verify_password(new_password, user.password_hash):
        raise HTTPException(422, 'New password must differ from current password')
    before = {'user_id': user.id, 'generation': credential.generation, 'must_change_password': credential.must_change_password}
    user.password_hash = hash_password(new_password)
    credential.generation += 1
    credential.must_change_password = False
    state = await session.get(AccessState, 1)
    await _audit(session, state, user.id, 'user.password_change', 'Authenticated password change', before,
                 {'user_id': user.id, 'generation': credential.generation, 'must_change_password': False})
    return {'reauthenticate': True}

@atomic_mutation
async def set_active(session, *, actor, revision, reason, user_id, active):
    from app.authorization.service import set_user_active
    await set_user_active(session, actor=actor, revision=revision, reason=reason, user_id=user_id, active=active)
    credential = await session.get(AccountCredential, user_id, populate_existing=True)
    if credential is not None:
        credential.generation += 1  # Reactivation must not resurrect an old session.
    await session.flush()
