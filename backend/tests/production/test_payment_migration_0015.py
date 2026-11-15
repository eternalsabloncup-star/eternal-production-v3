"""Alembic 0014→0015 payment monitor columns on disposable PostgreSQL only."""

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
    assert name.endswith("_test") and name.startswith("epv3_pay_")
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
    name = "epv3_pay_" + uuid.uuid4().hex[:12] + "_test"
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
        migrate("20261118_0014")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO production_jobs "
                    "(accurate_so_number, branch_id, design_status, payment_status, "
                    "sample_status, processing_status) "
                    "VALUES ('SO-P15', 'A', 'pending', 'pending', 'not_required', 'Baru')"
                )
            )
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


def test_0015_upgrade_adds_columns_and_downgrades(database):
    engine, migrate = database
    migrate("20261119_0015")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261119_0015"
        assert conn.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name='payment_receipt_refs' AND column_name='paid_at'"
            )
        ) == 1
        assert conn.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name='payment_bypasses' AND column_name='idempotency_key'"
            )
        ) == 1
        assert conn.scalar(
            text(
                "SELECT payment_review_required FROM production_jobs WHERE accurate_so_number='SO-P15'"
            )
        ) is False
    migrate("20261118_0014", "downgrade")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261118_0014"
        assert conn.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name='production_jobs' AND column_name='payment_review_required'"
            )
        ) == 0
