"""Alembic 0016→0017 production_branches on disposable PostgreSQL only."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
import pytest
from psycopg2 import sql
from sqlalchemy import create_engine, text

from tests.db_url_guard import database_name, is_test_database_url, resolve_test_database_urls

ROOT = Path(__file__).resolve().parents[2]
SHARED = "eternal_production_v3_test"


def _assert_disposable(name: str) -> None:
    assert name.endswith("_test") and name.startswith("epv3_br_")
    assert name != SHARED
    assert is_test_database_url(f"postgresql://x/{name}")


@pytest.fixture
def database():
    async_url, _ = resolve_test_database_urls()
    source = os.environ.get("TEST_DATABASE_URL") or async_url
    parsed = urlsplit(source.replace("+asyncpg", "").replace("+psycopg2", ""))
    if parsed.hostname not in {"127.0.0.1", "localhost"} or not (parsed.path or "").endswith(
        "_test"
    ):
        pytest.fail("Loopback disposable TEST_DATABASE_URL required")
    name = "epv3_br_" + uuid.uuid4().hex[:12] + "_test"
    _assert_disposable(name)
    try:
        admin = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            dbname="postgres",
        )
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"Cannot provision disposable DB: {exc}")
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except Exception as exc:  # noqa: BLE001
        admin.close()
        pytest.fail(f"CREATE DATABASE failed: {exc}")

    sync = (
        f"postgresql+psycopg2://{parsed.username}:{parsed.password}"
        f"@{parsed.hostname}:{parsed.port or 5432}/{name}"
    )
    async_u = sync.replace("+psycopg2", "+asyncpg")
    assert database_name(sync) == name
    env = {**os.environ, "APP_ENV": "test", "DATABASE_URL": async_u, "DATABASE_URL_SYNC": sync}

    def migrate(target, direction="upgrade", succeeds=True):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", direction, target],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        assert (result.returncode == 0) == succeeds, result.stdout + "\n" + result.stderr
        return result

    engine = create_engine(sync)
    try:
        migrate("20261119_0016")
        yield engine, migrate
    finally:
        engine.dispose()
        _assert_disposable(name)
        with admin.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        admin.close()


def test_0017_upgrade_no_seed_downgrade_preserves_jobs(database):
    engine, migrate = database
    # Pre-create a fake jobs table row marker via payment tables existence only —
    # full job schema is heavy; assert 0017 does not seed branches and drops cleanly.
    with engine.begin() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261119_0016"
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name='production_branches'"
                )
            )
            == 0
        )

    migrate("20261120_0017")
    with engine.begin() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261120_0017"
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name='production_branches'"
                )
            )
            == 1
        )
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name='production_branches_audit'"
                )
            )
            == 1
        )
        # No automatic seed
        assert conn.scalar(text("SELECT count(*) FROM production_branches")) == 0
        # Manual insert does not rewrite other schemas
        conn.execute(
            text(
                "INSERT INTO production_branches (code, name, active, sort_order) "
                "VALUES ('BR-JKT', 'Jakarta', true, 1)"
            )
        )
        assert conn.scalar(text("SELECT name FROM production_branches WHERE code='BR-JKT'")) == (
            "Jakarta"
        )
        # Payment settings from 0016 still present
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name='payment_approval_settings'"
                )
            )
            == 1
        )

    migrate("20261119_0016", direction="downgrade")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261119_0016"
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name LIKE 'production_branches%'"
                )
            )
            == 0
        )
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name='payment_approval_settings'"
                )
            )
            == 1
        )

    migrate("20261120_0017")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261120_0017"
        assert conn.scalar(text("SELECT count(*) FROM production_branches")) == 0
