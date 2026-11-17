"""Alembic 0013→0014 lifecycle + partial UNIQUE on an exclusive disposable test DB.

Provisions via CI-supported TEST_DATABASE_URL credentials (same pattern as
payment / operations migration tests). Never uses sudo or peer-admin sockets.
Never mutates staging/Live and never wipes the shared public test schema.
"""

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
SHARED_TEST_DB = "eternal_production_v3_test"


def _assert_disposable_db_name(name: str) -> None:
    """Fail closed before any DROP/CREATE against non-disposable databases."""
    assert name.endswith("_test"), f"refusing non-test database name={name!r}"
    assert name.startswith("epv3_life_"), f"refusing non-disposable name={name!r}"
    assert name != SHARED_TEST_DB, "refusing shared CI/public test database"
    assert is_test_database_url(f"postgresql://x/{name}"), f"guard rejected {name!r}"


@pytest.fixture
def database():
    async_url, sync_url = resolve_test_database_urls()
    # Prefer explicit TEST_* / CI loopback credentials.
    source = os.environ.get("TEST_DATABASE_URL") or async_url
    parsed = urlsplit(source.replace("+asyncpg", "").replace("+psycopg2", ""))
    if parsed.hostname not in {"127.0.0.1", "localhost"} or not (parsed.path or "").endswith(
        "_test"
    ):
        pytest.fail(
            "Isolated disposable migration DB requires loopback PostgreSQL "
            "TEST_DATABASE_URL ending in _test (cannot provision safely)"
        )

    user = parsed.username
    password = parsed.password
    host = parsed.hostname
    port = parsed.port or 5432
    name = "epv3_life_" + uuid.uuid4().hex[:12] + "_test"
    _assert_disposable_db_name(name)

    try:
        admin = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname="postgres",
        )
    except Exception as exc:  # noqa: BLE001 — surface provisioning failure, do not skip
        pytest.fail(f"Cannot connect to postgres maintenance DB for disposable test: {exc}")
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except Exception as exc:  # noqa: BLE001
        admin.close()
        pytest.fail(
            "Cannot CREATE disposable migration database via CI-supported credentials "
            f"(need CREATEDB/superuser on test role): {exc}"
        )

    sync = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"
    async_u = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"
    assert database_name(sync) == name
    env = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_URL": async_u,
        "DATABASE_URL_SYNC": sync,
    }

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
        migrate("20261117_0013")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO production_jobs "
                    "(accurate_so_number, branch_id, design_status, payment_status, "
                    "sample_status, processing_status) "
                    "VALUES ('SO-MIG-1', 'A', 'pending', 'pending', 'not_required', 'Baru')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO job_line_qtys (job_id, so_line_id, po_qty, production_process) "
                    "VALUES (1, 'L1', 10, 'print')"
                )
            )
        yield engine, migrate
    finally:
        engine.dispose()
        _assert_disposable_db_name(name)
        with admin.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        admin.close()


def test_0014_upgrade_partial_unique_and_safe_downgrade(database):
    engine, migrate = database
    with engine.connect() as conn:
        before_jobs = conn.execute(
            text("SELECT id, accurate_so_number, branch_id FROM production_jobs ORDER BY id")
        ).all()
        before_lines = conn.execute(
            text("SELECT id, job_id, so_line_id, po_qty FROM job_line_qtys ORDER BY id")
        ).all()
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261117_0013"

    migrate("20261118_0014")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261118_0014"
        assert (
            conn.execute(
                text("SELECT id, accurate_so_number, branch_id FROM production_jobs ORDER BY id")
            ).all()
            == before_jobs
        )
        assert (
            conn.execute(
                text("SELECT id, job_id, so_line_id, po_qty FROM job_line_qtys ORDER BY id")
            ).all()
            == before_lines
        )
        assert (
            conn.scalar(
                text(
                    "SELECT lifecycle_status FROM production_jobs WHERE accurate_so_number='SO-MIG-1'"
                )
            )
            == "active"
        )
        assert (
            conn.scalar(text("SELECT line_status FROM job_line_qtys WHERE so_line_id='L1'"))
            == "active"
        )

    with pytest.raises(Exception):
        with engine.begin() as bad:
            bad.execute(
                text(
                    "INSERT INTO production_jobs "
                    "(accurate_so_number, branch_id, design_status, payment_status, "
                    "sample_status, processing_status, lifecycle_status) "
                    "VALUES ('SO-MIG-1', 'A', 'pending', 'pending', 'not_required', 'Baru', 'active')"
                )
            )
    with engine.begin() as conn2:
        conn2.execute(
            text("UPDATE production_jobs SET lifecycle_status='cancelled' WHERE id=1")
        )
        conn2.execute(
            text(
                "INSERT INTO production_jobs "
                "(accurate_so_number, branch_id, design_status, payment_status, "
                "sample_status, processing_status, lifecycle_status) "
                "VALUES ('SO-MIG-1', 'A', 'pending', 'pending', 'not_required', 'Baru', 'active')"
            )
        )

    migrate("20261117_0013", "downgrade", succeeds=False)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261118_0014"
        assert (
            conn.scalar(
                text("SELECT count(*) FROM production_jobs WHERE lifecycle_status='cancelled'")
            )
            == 1
        )

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM production_jobs WHERE lifecycle_status='active'"))
        conn.execute(
            text(
                "UPDATE production_jobs SET lifecycle_status='active', "
                "cancelled_at=NULL, cancel_reason=NULL, cancel_gate=NULL, cancelled_by_user_id=NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE job_line_qtys SET line_status='active', revision_note=NULL, "
                "removed_from_source_at=NULL"
            )
        )
    migrate("20261117_0013", "downgrade")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261117_0013"
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name='production_jobs' AND column_name='lifecycle_status'"
                )
            )
            == 0
        )
