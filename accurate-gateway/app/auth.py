"""M2M Bearer auth for Production V3 → gateway only."""

from __future__ import annotations

from fastapi import Header, HTTPException

from app.config import get_settings


async def require_m2m(
    authorization: str | None = Header(default=None),
) -> None:
    settings = get_settings()
    expected = (settings.gateway_m2m_token or "").strip()
    if not expected:
        raise HTTPException(
            503,
            detail={
                "code": "gateway_m2m_unconfigured",
                "message": "GATEWAY_M2M_TOKEN belum dikonfigurasi",
            },
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            401,
            detail={"code": "m2m_missing", "message": "Bearer token wajib"},
        )
    token = authorization.split(" ", 1)[1].strip()
    if token != expected:
        raise HTTPException(
            403,
            detail={"code": "m2m_rejected", "message": "Token M2M ditolak"},
        )
