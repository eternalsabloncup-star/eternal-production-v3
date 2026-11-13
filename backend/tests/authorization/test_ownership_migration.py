from sqlalchemy import text
from tests.production.test_payment_migration import database

def test_0011_to_0012_preserves_history_and_refuses_destructive_downgrade(database):
    engine,migrate=database
    migrate('20261115_0011')
    with engine.begin() as c:
        before=c.execute(text('SELECT * FROM production_events')).all()
        c.execute(text("INSERT INTO users (id,username,display_name,role,password_hash,permissions,branch_ids,is_active) VALUES (1,'ownership-test','Historical','operator','unused','[]','[]',true)"))
    migrate('20261116_0012')
    with engine.connect() as c:
        assert c.execute(text('SELECT * FROM production_events')).all()==before
        assert c.scalar(text('SELECT count(*) FROM task_ownerships'))==0
    migrate('20261115_0011','downgrade')
    migrate('20261116_0012')
    with engine.begin() as c:
        c.execute(text("INSERT INTO task_ownerships(job_id,user_id,task_kind,active,created_by) VALUES (1,1,'operator',true,1)"))
    migrate('20261115_0011','downgrade',succeeds=False)
    with engine.connect() as c:
        assert c.scalar(text('SELECT version_num FROM alembic_version'))=='20261116_0012'
        assert c.scalar(text('SELECT count(*) FROM task_ownerships'))==1
        assert c.execute(text('SELECT * FROM production_events')).all()==before
