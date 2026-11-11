"""Health and readiness endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import check_database_connection

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str


class ReadyResponse(BaseModel):
    status: str
    database: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=__version__,
        environment=settings.app_env,
    )


@router.get("/ready", response_model=ReadyResponse)
async def ready() -> ReadyResponse:
    try:
        ok = await check_database_connection()
    except Exception as exc:  # noqa: BLE001 - surface readiness failure cleanly
        raise AppError(
            "Database connection failed",
            code="database_unavailable",
            status_code=503,
            details={"reason": str(exc.__class__.__name__)},
        ) from exc

    if not ok:
        raise AppError(
            "Database health check failed",
            code="database_unhealthy",
            status_code=503,
        )

    return ReadyResponse(status="ready", database="ok")
