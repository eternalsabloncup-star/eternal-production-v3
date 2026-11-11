"""Fail-closed resolution of PostgreSQL URLs for automated tests."""

from __future__ import annotations

import os
from urllib.parse import urlparse

LOCAL_TEST_ASYNC = (
    "postgresql+asyncpg://epv3_test:epv3_test_local_only"
    "@127.0.0.1:5432/eternal_production_v3_test"
)
LOCAL_TEST_SYNC = (
    "postgresql+psycopg2://epv3_test:epv3_test_local_only"
    "@127.0.0.1:5432/eternal_production_v3_test"
)


def database_name(url: str) -> str:
    normalized = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    normalized = normalized.replace("postgresql+psycopg2://", "postgresql://", 1)
    path = urlparse(normalized).path or ""
    return path.lstrip("/")


def is_test_database_url(url: str) -> bool:
    """Fail-closed allowlist: only dedicated test database names."""
    name = database_name(url).lower()
    if not name:
        return False
    if name.endswith("_test"):
        return True
    return name == "eternal_production_v3_test"


def reject_non_test_url(url: str, source: str) -> None:
    if not is_test_database_url(url):
        raise RuntimeError(
            f"{source} is not a dedicated test database "
            f"(resolved database={database_name(url)!r}). "
            "Refusing to run tests against development/production databases."
        )


def async_to_sync_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg2://" + url.removeprefix("postgresql+asyncpg://")
    return url


def resolve_test_database_urls() -> tuple[str, str]:
    """Prefer explicit TEST_* URLs; else respect CI DATABASE_URL if test-only.

    Never fall through silently to a development/production database.
    """
    test_async = os.environ.get("TEST_DATABASE_URL")
    test_sync = os.environ.get("TEST_DATABASE_URL_SYNC")
    if test_async:
        reject_non_test_url(test_async, "TEST_DATABASE_URL")
        sync = test_sync or async_to_sync_url(test_async)
        reject_non_test_url(sync, "TEST_DATABASE_URL_SYNC")
        return test_async, sync

    env_async = os.environ.get("DATABASE_URL")
    env_sync = os.environ.get("DATABASE_URL_SYNC")
    if env_async:
        reject_non_test_url(env_async, "DATABASE_URL")
        sync = env_sync or async_to_sync_url(env_async)
        reject_non_test_url(sync, "DATABASE_URL_SYNC")
        return env_async, sync

    return LOCAL_TEST_ASYNC, LOCAL_TEST_SYNC
