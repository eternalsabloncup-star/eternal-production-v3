"""Pytest fixtures for backend foundation tests."""

import os

import pytest
from httpx import ASGITransport, AsyncClient

# Force dedicated test DB credentials (override any shell/.env development values).
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://epv3_test:epv3_test_local_only@127.0.0.1:5432/eternal_production_v3_test",
)
os.environ["DATABASE_URL_SYNC"] = os.environ.get(
    "TEST_DATABASE_URL_SYNC",
    "postgresql+psycopg2://epv3_test:epv3_test_local_only@127.0.0.1:5432/eternal_production_v3_test",
)
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
