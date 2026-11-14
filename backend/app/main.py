"""FastAPI application entrypoint for ETERNAL PRODUCTION V3."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.customer_portal import router as customer_portal_router
from app.api.health import router as health_router
from app.api.production.payroll import router as production_payroll_router
from app.api.production.workflow import router as production_workflow_router
from app.api.production_inbox import router as production_inbox_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    # Register additive metadata even when Settings is disabled. This performs
    # no DB access and keeps ORM schema management aware of foreign keys.
    from app.authorization import models as access_models  # noqa: F401
    from app.authorization.ownership import TaskOwnership  # noqa: F401
    from app.authorization.accounts import AccountCredential  # noqa: F401
    settings = get_settings()
    if settings.v3_workflow_authorization not in {"legacy", "enforced"}:
        raise RuntimeError("Unknown workflow authorization mode")
    if settings.v3_workflow_authorization == "enforced" and (not settings.v3_settings_enabled or settings.app_env != "test"):
        raise RuntimeError("Workflow cutover is restricted to Settings-enabled test sandbox")
    application = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if settings.v3_settings_enabled:
        from app.authorization.api import router as settings_router
        application.include_router(settings_router, prefix=settings.api_prefix)
    if settings.v3_settings_enabled and settings.v3_workflow_authorization == "enforced":
        from app.authorization.workflow_api import router as workflow_access_router
        application.include_router(workflow_access_router, prefix=settings.api_prefix)
    register_exception_handlers(application)
    application.include_router(health_router, prefix=settings.api_prefix)
    application.include_router(auth_router, prefix=settings.api_prefix)
    application.include_router(production_inbox_router, prefix=settings.api_prefix)
    application.include_router(
        production_workflow_router, prefix=settings.api_prefix
    )
    application.include_router(
        production_payroll_router, prefix=settings.api_prefix
    )
    from app.api.production.operations import router as production_operations_router
    application.include_router(
        production_operations_router, prefix=settings.api_prefix
    )
    # Local customer portal (/t/...) — isolated; not a public deploy in this task.
    application.include_router(customer_portal_router)
    return application


app = create_app()
