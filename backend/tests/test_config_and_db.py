"""Configuration and database connectivity tests."""

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import check_database_connection, get_engine


def test_settings_load_from_environment() -> None:
    settings = get_settings()
    assert settings.app_env == "test"
    assert "eternal_production_v3_test" in settings.database_url
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_metadata_has_no_business_tables_yet() -> None:
    # Baseline foundation: no production workflow entities.
    assert Base.metadata.tables == {}


@pytest.mark.asyncio
async def test_database_connection() -> None:
    assert await check_database_connection() is True


@pytest.mark.asyncio
async def test_database_select_one() -> None:
    engine = get_engine()
    async with engine.connect() as connection:
        value = (await connection.execute(text("SELECT 1"))).scalar_one()
    assert value == 1
