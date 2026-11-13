"""Reuse disposable database provisioning; test real Alembic Settings migration."""
import importlib.util
from pathlib import Path
from sqlalchemy import text
from tests.production.test_payment_migration import database


def test_settings_upgrade_downgrade_existing_grants_and_history(database):
    engine, migrate = database
    migrate('20261114_0010')
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (username,display_name,role,password_hash,permissions,branch_ids,is_active) VALUES ('existing','Existing','Direktur','pbkdf2-test-fixture','[\"production.job.read\"]','[\"A\"]',true)"))
        before = conn.execute(text('SELECT * FROM users')).all()
        history = conn.execute(text('SELECT * FROM production_events')).all()
    migrate('20261115_0011')
    with engine.connect() as conn:
        assert conn.execute(text('SELECT * FROM users')).all()==before
        assert conn.execute(text('SELECT * FROM production_events')).all()==history
        assert conn.scalar(text('SELECT count(*) FROM access_groups'))==0
        assert conn.scalar(text('SELECT count(*) FROM access_memberships'))==0
        assert conn.scalar(text('SELECT count(*) FROM access_grants'))==0
        assert conn.execute(text('SELECT generation,must_change_password FROM access_account_credentials')).all()==[(1,False)]
    migrate('20261114_0010','downgrade')
    with engine.connect() as conn: assert conn.execute(text('SELECT * FROM users')).all()==before
    migrate('20261115_0011')
    with engine.begin() as conn: conn.execute(text('UPDATE access_state SET bootstrapped=true WHERE id=1'))
    migrate('20261114_0010','downgrade',succeeds=False)
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT version_num FROM alembic_version'))=='20261115_0011'
        assert conn.scalar(text('SELECT bootstrapped FROM access_state WHERE id=1'))


def test_settings_preflight_failure_is_atomic(database):
    engine, migrate = database
    migrate('20261114_0010')
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (username,display_name,role,password_hash,permissions,branch_ids,is_active) VALUES ('','Bad','operator','x','[]','[]',true)"))
    migrate('20261115_0011',succeeds=False)
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT version_num FROM alembic_version'))=='20261114_0010'
        assert conn.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_name LIKE 'access_%'"))==0
