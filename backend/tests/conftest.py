"""Pytest fixtures for backend foundation tests."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from tests.db_url_guard import resolve_test_database_urls

_async_url, _sync_url = resolve_test_database_urls()
os.environ["DATABASE_URL"] = _async_url
os.environ["DATABASE_URL_SYNC"] = _sync_url
os.environ["APP_ENV"] = "test"
os.environ["APP_DEBUG"] = "false"

from app.core.config import get_settings
from app.db.session import dispose_engine
from app.main import create_app

get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def _reset_engine_per_test():
    """Avoid asyncpg connections attached to a closed event loop across tests."""
    await dispose_engine()
    get_settings.cache_clear()
    yield
    await dispose_engine()
    get_settings.cache_clear()


@pytest.fixture
async def client():
    application = create_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _legacy_fixtures_without_synced_lines(request, monkeypatch):
    """Pre-cap fixtures schedule before any PO line exists; cap tests opt back in."""
    from app.services.production import engine

    if "production_defaults" in request.keywords:
        return
    if "strict_line_qty" not in request.keywords:
        monkeypatch.setattr(engine, "REQUIRE_SYNCED_LINE_QTY", False)
    if "strict_loading_cap" not in request.keywords:
        monkeypatch.setattr(engine, "ENFORCE_LOADING_PACKING_CAP", False)
