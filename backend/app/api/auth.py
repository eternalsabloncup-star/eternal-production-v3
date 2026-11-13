"""V3 authentication endpoints — dedicated secrets only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    assert_legacy_auth_available,
    get_current_user,
    require_jwt_secret,
    require_password_pepper,
    verify_password,
)
from app.db.session import get_db_session
from app.core.config import get_settings
from app.models.user import User
from app.services.audit import record_auth_event

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=200)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    display_name: str
    role: str
    permissions: list[str]
    branch_ids: list[str]
    settings_enabled: bool = False
    system_director: bool = False
    must_change_password: bool = False
    authorization_revision: int | None = None
    workflow_authorization: str = "legacy"


class MeResponse(BaseModel):
    user_id: int
    username: str
    display_name: str
    role: str
    permissions: list[str]
    branch_ids: list[str]
    settings_enabled: bool = False
    system_director: bool = False
    must_change_password: bool = False
    authorization_revision: int | None = None
    workflow_authorization: str = "legacy"


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    if get_settings().v3_settings_enabled:
        from app.authorization import accounts
        try:
            result = await accounts.authenticate(session, body.username.strip(), body.password.get_secret_value())
        except HTTPException:
            await record_auth_event(session, event_type="login", username=body.username.strip(),
                result="failed", detail="managed_login_rejected",
                client_host=request.client.host if request.client else None)
            raise
        access = await accounts.session_user(session, result['access_token'], allow_password_change=True)
        user = await session.get(User, access.user_id)
        await record_auth_event(session, event_type="login", username=user.username, user_id=user.id,
            result="ok", client_host=request.client.host if request.client else None)
        return LoginResponse(**result, user_id=user.id, username=user.username, display_name=user.display_name,
            role=user.role, permissions=list(user.permissions or []), branch_ids=list(user.branch_ids or []),
            settings_enabled=True, system_director=access.director, authorization_revision=access.revision,
            workflow_authorization=get_settings().v3_workflow_authorization)
    await assert_legacy_auth_available(session)
    require_jwt_secret()
    require_password_pepper()
    host = request.client.host if request.client else None
    result = await session.execute(
        select(User).where(User.username == body.username.strip())
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        await record_auth_event(
            session,
            event_type="login",
            username=body.username.strip(),
            result="failed",
            detail="unknown_or_inactive_user",
            client_host=host,
        )
        raise HTTPException(401, "Username atau password salah")
    if not verify_password(body.password.get_secret_value(), user.password_hash):
        await record_auth_event(
            session,
            event_type="login",
            username=user.username,
            user_id=user.id,
            result="failed",
            detail="bad_password",
            client_host=host,
        )
        raise HTTPException(401, "Username atau password salah")
    token = create_access_token(user)
    await record_auth_event(
        session,
        event_type="login",
        username=user.username,
        user_id=user.id,
        result="ok",
        client_host=host,
    )
    return LoginResponse(
        access_token=token,
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        permissions=list(user.permissions or []),
        branch_ids=list(user.branch_ids or []),
    )


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        permissions=list(user.permissions or []),
        branch_ids=list(user.branch_ids or []),
        settings_enabled=get_settings().v3_settings_enabled,
        workflow_authorization=get_settings().v3_workflow_authorization,
        system_director=bool(getattr(user, '_managed_access', None) and user._managed_access.director),
        must_change_password=getattr(user, '_must_change_password', False),
        authorization_revision=getattr(getattr(user, '_managed_access', None), 'revision', None),
    )
