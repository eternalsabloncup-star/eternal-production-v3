"""V3-only authentication helpers. Never reuse ERP V1 JWT_SECRET."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)

PERM_INBOX_READ = "production.inbox.read"
PERM_ORDER_READ = "production.order.read"

_PLACEHOLDER_SECRETS = {
    "",
    "change_me",
    "replace_with_v3_jwt_secret",
    "replace_with_v3_password_pepper",
}


def require_jwt_secret(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    if not cfg.v3_jwt_secret or cfg.v3_jwt_secret in _PLACEHOLDER_SECRETS:
        raise HTTPException(
            503, "Autentikasi V3 belum dikonfigurasi (V3_JWT_SECRET)"
        )
    return cfg.v3_jwt_secret


def require_password_pepper(settings: Settings | None = None) -> str:
    """Password hashing material — must differ from JWT signing key."""
    cfg = settings or get_settings()
    if not cfg.v3_password_pepper or cfg.v3_password_pepper in _PLACEHOLDER_SECRETS:
        raise HTTPException(
            503, "Autentikasi V3 belum dikonfigurasi (V3_PASSWORD_PEPPER)"
        )
    if cfg.v3_password_pepper == cfg.v3_jwt_secret:
        raise HTTPException(
            503,
            "V3_PASSWORD_PEPPER harus berbeda dari V3_JWT_SECRET",
        )
    return cfg.v3_password_pepper


def hash_password(password: str, *, settings: Settings | None = None) -> str:
    """PBKDF2-HMAC with dedicated pepper + per-password random salt.

    Stored format: pbkdf2_sha256$iterations$salt_hex$digest_hex
    """
    pepper = require_password_pepper(settings)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt + pepper.encode("utf-8"),
        120_000,
    )
    return f"pbkdf2_sha256$120000${salt.hex()}${digest.hex()}"


def verify_password(
    password: str, password_hash: str, *, settings: Settings | None = None
) -> bool:
    try:
        algo, iter_s, salt_hex, digest_hex = password_hash.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iter_s)
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    pepper = require_password_pepper(settings)
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt + pepper.encode("utf-8"),
        iterations,
    )
    return hmac.compare_digest(candidate.hex(), digest_hex)


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
    async def _dep(
        request: Request,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_db_session),
    ) -> User:
        have = set(user.permissions or [])
        if not set(needed).issubset(have):
            from app.services.audit import record_auth_event

            await record_auth_event(
                session,
                event_type="permission_denied",
                username=user.username,
                user_id=user.id,
                result="forbidden",
                detail=",".join(needed),
                client_host=request.client.host if request.client else None,
            )
            raise HTTPException(403, "Izin tidak mencukupi")
        return user

    return _dep


def user_can_access_branch(user: User, branch_id: str | None) -> bool:
    allowed = list(user.branch_ids or [])
    if not allowed:
        return False
    if branch_id is None or branch_id == "":
        return False
    return branch_id in allowed
