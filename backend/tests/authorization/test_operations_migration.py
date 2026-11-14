"""Migration 0013 on a disposable PostgreSQL database."""
from sqlalchemy import text
from tests.production.test_payment_migration import database


def test_operations_upgrade_preserves_data_and_downgrade_guards(database):
    engine, migrate = database
    migrate('20261116_0012')
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (username,display_name,role,password_hash,permissions,branch_ids,is_active) VALUES ('keep','Keep','Direktur','pbkdf2-test-fixture','[]','[\"A\"]',true)"))
        before = conn.execute(text('SELECT * FROM users')).all()
    migrate('20261117_0013')
    with engine.connect() as conn:
        assert conn.execute(text('SELECT * FROM users')).all() == before
        for t in ('production_machines', 'delivery_plans', 'delivery_plan_events'):
            assert conn.scalar(text(f'SELECT count(*) FROM {t}')) == 0
        cols = {r[0] for r in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name IN ('job_line_qtys','schedule_assignments')"))}
        assert {'source_qty', 'drift_detected_at', 'operator_user_id'} <= cols
    migrate('20261116_0012', 'downgrade')
    with engine.connect() as conn:
        assert conn.execute(text('SELECT * FROM users')).all() == before
        assert conn.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_name='production_machines'")) == 0
    migrate('20261117_0013')
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO production_machines (branch_id,name,kind,capacity_per_shift,shifts_per_day,active,created_by) VALUES ('A','M1','auto',100,1,true,(SELECT id FROM users LIMIT 1))"))
    migrate('20261116_0012', 'downgrade', succeeds=False)
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT version_num FROM alembic_version')) == '20261117_0013'
        assert conn.scalar(text('SELECT count(*) FROM production_machines')) == 1
