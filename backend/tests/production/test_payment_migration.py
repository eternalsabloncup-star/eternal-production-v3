"""Real Alembic 0009->0010 on disposable loopback PostgreSQL databases."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import uuid
from urllib.parse import urlsplit

import psycopg2
from psycopg2 import sql
import pytest
from sqlalchemy import create_engine, text
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / 'alembic/versions/20261114_0010_payment_evidence.py'

def module():
    spec = importlib.util.spec_from_file_location('payment_migration', MIGRATION)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result

@pytest.fixture
def database():
    parsed = urlsplit(os.environ.get('TEST_DATABASE_URL', ''))
    if parsed.hostname != '127.0.0.1' or not parsed.path.endswith('_test'):
        pytest.skip('Explicit loopback PostgreSQL test URL required')
    name = 'epv3_p0_' + uuid.uuid4().hex[:12] + '_test'
    admin = psycopg2.connect(host='127.0.0.1', port=parsed.port, user=parsed.username, password=parsed.password, dbname='postgres')
    admin.autocommit = True
    with admin.cursor() as cur: cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    base = os.environ['TEST_DATABASE_URL'].rsplit('/', 1)[0]
    url = base + '/' + name
    env = {**os.environ, 'APP_ENV': 'test', 'DATABASE_URL': url, 'DATABASE_URL_SYNC': url.replace('+asyncpg', '+psycopg2')}
    def migrate(target, direction='upgrade', succeeds=True):
        result = subprocess.run([sys.executable, '-m', 'alembic', direction, target], cwd=ROOT, env=env, text=True, capture_output=True)
        assert (result.returncode == 0) == succeeds, result.stderr
        return result
    engine = create_engine(env['DATABASE_URL_SYNC'])
    try:
        migrate('20261113_0009')
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO production_jobs (id,accurate_so_number,branch_id,payment_status) VALUES (1,'P0-MIGRATION-1','TEST','approved'),(2,'P0-MIGRATION-2','TEST','approved')"))
            conn.execute(text("INSERT INTO payment_receipt_refs (job_id,accurate_receipt_id,status,amount,recorded_by) VALUES (1,'900','valid',10,1),(2,'901','invalidated',-1,1),(1,'902','valid',0,1),(1,'903','valid',-1,1)"))
            conn.execute(text("INSERT INTO production_events (job_id,event_type,qty_physical,idempotency_key,actor_user_id) VALUES (1,'output_confirmed',25,'migration-history',1)"))
        yield engine, migrate
    finally:
        engine.dispose()
        with admin.cursor() as cur: cur.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
        admin.close()

def snapshot(conn):
    return (conn.execute(text('SELECT id,job_id,accurate_receipt_id,status,amount FROM payment_receipt_refs ORDER BY id')).all(),
            conn.execute(text('SELECT * FROM production_events ORDER BY id')).all())

def assert_0009(conn):
    assert conn.scalar(text('SELECT version_num FROM alembic_version')) == '20261113_0009'
    assert conn.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_name='payment_receipt_refs' AND column_name IN ('evidence_verified','idempotency_key')")) == 0


def test_preflight_upgrade_downgrade_history_and_constraints(database):
    engine, migrate = database
    with engine.connect() as conn:
        before = snapshot(conn)
        report = module().preflight(conn)
        assert report['affected_job_ids'] == [1] and report['legacy_evidence_verified'] is False
        assert report['duplicate_active_receipts'] == []
    migrate('20261114_0010')
    with engine.connect() as conn:
        assert snapshot(conn) == before
        assert conn.execute(text('SELECT evidence_verified,idempotency_key FROM payment_receipt_refs')).all() == [(False, None)] * 4
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO payment_receipt_refs (job_id,accurate_receipt_id,status,recorded_by) VALUES (2,'900','valid',1)"))
    with engine.begin() as conn:
        conn.execute(text("UPDATE payment_receipt_refs SET idempotency_key='request-key' WHERE accurate_receipt_id='900'"))
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO payment_receipt_refs (job_id,accurate_receipt_id,status,recorded_by,idempotency_key) VALUES (1,'904','valid',1,'request-key')"))
    migrate('20261113_0009', 'downgrade')
    with engine.connect() as conn:
        assert_0009(conn); assert snapshot(conn) == before
    migrate('20261114_0010')

@pytest.mark.parametrize('rid', ['900', ''])
def test_duplicate_or_blank_identity_fails_atomically(database, rid):
    engine, migrate = database
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO payment_receipt_refs (job_id,accurate_receipt_id,status,amount,recorded_by) VALUES (2,:rid,'valid',0,1)"), {'rid': rid})
        before = snapshot(conn)
        report = module().preflight(conn)
        assert report['affected_job_ids'] == [1, 2]
        if rid: assert report['duplicate_active_receipts'][0]['job_ids'] == [1, 2]
        else: assert report['invalid_receipt_ids']
    migrate('20261114_0010', succeeds=False)
    with engine.connect() as conn:
        assert_0009(conn); assert snapshot(conn) == before


def test_late_ddl_failure_rolls_back_all_columns_indexes_and_data(database, monkeypatch):
    engine, _ = database
    m = module()
    with engine.connect() as conn: before = snapshot(conn)
    with pytest.raises(RuntimeError, match='Injected late failure'):
        with engine.begin() as conn:
            ops = Operations(MigrationContext.configure(conn))
            original = ops.create_index
            def fail(*args, **kwargs):
                original(*args, **kwargs)
                raise RuntimeError('Injected late failure')
            monkeypatch.setattr(ops, 'create_index', fail)
            monkeypatch.setattr(m, 'op', ops)
            m.upgrade()
    with engine.connect() as conn:
        assert_0009(conn); assert snapshot(conn) == before
        assert conn.scalar(text("SELECT count(*) FROM pg_indexes WHERE indexname LIKE 'uq_payment_receipt_%'")) == 0


def test_migration_lock_blocks_receipt_writes_through_index_creation(database, monkeypatch):
    from sqlalchemy.exc import OperationalError, IntegrityError
    engine, _ = database
    m = module()
    with engine.begin() as conn:
        monkeypatch.setattr(m, 'op', Operations(MigrationContext.configure(conn)))
        m.upgrade()
        with pytest.raises(OperationalError) as error:
            with engine.begin() as writer:
                writer.execute(text("SET LOCAL lock_timeout = '100ms'"))
                writer.execute(text("INSERT INTO payment_receipt_refs (job_id,accurate_receipt_id,status,recorded_by) VALUES (2,'900','valid',1)"))
        assert error.value.orig.pgcode == '55P03'
    with pytest.raises(IntegrityError):
        with engine.begin() as writer:
            writer.execute(text("INSERT INTO payment_receipt_refs (job_id,accurate_receipt_id,status,recorded_by) VALUES (2,'900','valid',1)"))
