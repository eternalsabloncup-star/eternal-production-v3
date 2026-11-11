"""V3-only authentication helpers. Never reuse ERP V1 JWT_SECRET."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)

PERM_INBOX_READ = "production.inbox.read"
PERM_ORDER_READ = "production.order.read"


def hash_password(password: str, *, settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    secret = cfg.v3_jwt_secret.encode("utf-8")
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), secret, 120_000
    )
    return digest.hex()


def verify_password(
    password: str, password_hash: str, *, settings: Settings | None = None
) -> bool:
    candidate = hash_password(password, settings=settings)
    return hmac.compare_digest(candidate, password_hash)


def require_jwt_secret(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    if not cfg.v3_jwt_secret or cfg.v3_jwt_secret in {
        "",
        "change_me",
        "replace_with_v3_jwt_secret",
    }:
        raise HTTPException(
            503, "Autentikasi V3 belum dikonfigurasi (V3_JWT_SECRET)"
        )
    return cfg.v3_jwt_secret


def create_access_token(
    user: User, *, settings: Settings | None = None
) -> str:
    cfg = settings or get_settings()
    secret = require_jwt_secret(cfg)
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "permissions": list(user.permissions or []),
        "branch_ids": list(user.branch_ids or []),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=cfg.v3_jwt_hours)).timestamp()),
        "iss": "eternal-production-v3",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(
    token: str, *, settings: Settings | None = None
) -> dict[str, Any]:
    cfg = settings or get_settings()
    secret = require_jwt_secret(cfg)
    try:
        return jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer="eternal-production-v3",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Sesi tidak valid atau kedaluwarsa") from exc


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Autentikasi diperlukan")
    payload = decode_access_token(credentials.credentials, settings=settings)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(401, "Sesi tidak valid")
    result = await session.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(401, "Pengguna tidak aktif")
    return user


def require_permissions(*needed: str):
    async def _dep(user: User = Depends(get_current_user)) -> User:
        have = set(user.permissions or [])
        if not set(needed).issubset(have):
            raise HTTPException(403, "Izin tidak mencukupi")
        return user

    return _dep


def user_can_access_branch(user: User, branch_id: str | None) -> bool:
    allowed = list(user.branch_ids or [])
    if not allowed:
        return False
    if branch_id is None or branch_id == "":
        # Fail closed: unknown branch is not broadly allowed.
        return False
    return branch_id in allowed
