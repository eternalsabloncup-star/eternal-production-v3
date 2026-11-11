"""Audit helpers — never log secrets or raw tokens."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_audit import AuthAuditEvent


async def record_auth_event(
    session: AsyncSession,
    *,
    event_type: str,
    result: str,
    username: str | None = None,
    user_id: int | None = None,
    detail: str | None = None,
    client_host: str | None = None,
) -> None:
    # Strip anything that could look like a secret/token from detail.
    safe_detail = None
    if detail:
        safe_detail = detail[:200]
        for marker in ("Bearer ", "password", "token", "secret"):
            if marker.lower() in safe_detail.lower():
                safe_detail = "[redacted]"
                break
    session.add(
        AuthAuditEvent(
            event_type=event_type,
            user_id=user_id,
            username=username,
            result=result,
            detail=safe_detail,
            client_host=client_host,
        )
    )
    await session.commit()
