"""V3 authentication endpoints — dedicated secrets only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    get_current_user,
    require_jwt_secret,
    require_password_pepper,
    verify_password,
)
from app.db.session import get_db_session
from app.models.user import User
from app.services.audit import record_auth_event

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    display_name: str
    role: str
    permissions: list[str]
    branch_ids: list[str]


class MeResponse(BaseModel):
    user_id: int
    username: str
    display_name: str
    role: str
    permissions: list[str]
    branch_ids: list[str]


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
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
    if not verify_password(body.password, user.password_hash):
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
    )
