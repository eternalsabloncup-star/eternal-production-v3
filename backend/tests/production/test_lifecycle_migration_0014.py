"""Alembic 0013→0014 lifecycle + partial UNIQUE on an exclusive disposable test DB.

Creates/drops a dedicated loopback *_test database via local postgres peer auth.
Never mutates staging/Live and never wipes the shared public test schema.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from tests.db_url_guard import resolve_test_database_urls

ROOT = Path(__file__).resolve().parents[2]


def _admin_psql(sql_text: str) -> None:
    result = subprocess.run(
        ["sudo", "-n", "-u", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-c", sql_text],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


@pytest.fixture
def database():
    _, sync_url = resolve_test_database_urls()
    # Prefer CI/local epv3_test credentials from the resolved sync URL.
    # Example: postgresql+psycopg2://epv3_test:SECRET@127.0.0.1:5432/eternal_production_v3_test
    raw = sync_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    # Parse crudely but safely for this controlled URL shape.
    rest = raw.split("://", 1)[1]
    creds, hostdb = rest.rsplit("@", 1)
    user, password = creds.split(":", 1)
    hostport, _shared_db = hostdb.split("/", 1)
    host, port = (hostport.split(":") + ["5432"])[:2]
    if host not in {"127.0.0.1", "localhost"}:
        pytest.skip("Loopback disposable migration DB required")

    name = "epv3_life_" + uuid.uuid4().hex[:12] + "_test"
    # Owner must be epv3_test so alembic/app settings can connect.
    _admin_psql(f'CREATE DATABASE "{name}" OWNER "{user}"')
    _admin_psql(f'GRANT ALL PRIVILEGES ON DATABASE "{name}" TO "{user}"')

    sync = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"
    async_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"
    env = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_URL": async_url,
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
        # Terminate backends then drop disposable DB.
        _admin_psql(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{name}' AND pid <> pg_backend_pid()"
        )
        _admin_psql(f'DROP DATABASE IF EXISTS "{name}"')


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
