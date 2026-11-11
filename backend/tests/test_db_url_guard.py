"""Fail-closed database URL selection for tests."""

import pytest

from tests.db_url_guard import is_test_database_url, resolve_test_database_urls


def test_allows_dedicated_test_database_names() -> None:
    assert is_test_database_url(
        "postgresql+asyncpg://u:p@127.0.0.1:5432/eternal_production_v3_test"
    )
    assert is_test_database_url("postgresql+asyncpg://u:p@127.0.0.1:5432/orders_test")


def test_rejects_dev_and_production_database_names() -> None:
    assert not is_test_database_url(
        "postgresql+asyncpg://u:p@127.0.0.1:5432/eternal_production_v3_dev"
    )
    assert not is_test_database_url(
        "postgresql+asyncpg://u:p@127.0.0.1:5432/eternal_erp_v2"
    )


def test_prefers_explicit_test_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://ci:secret@127.0.0.1:5432/eternal_production_v3_test",
    )
    monkeypatch.delenv("TEST_DATABASE_URL_SYNC", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://dev:dev@127.0.0.1:5432/eternal_production_v3_dev",
    )
    async_url, sync_url = resolve_test_database_urls()
    assert "eternal_production_v3_test" in async_url
    assert sync_url.startswith("postgresql+psycopg2://")


def test_refuses_non_test_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL_SYNC", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://dev:dev@127.0.0.1:5432/eternal_production_v3_dev",
    )
    with pytest.raises(RuntimeError, match="Refusing to run tests"):
        resolve_test_database_urls()
