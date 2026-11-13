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
    settings = get_settings()
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
    # Local customer portal (/t/...) — isolated; not a public deploy in this task.
    application.include_router(customer_portal_router)
    return application


app = create_app()
