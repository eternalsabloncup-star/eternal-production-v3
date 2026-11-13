"""Additive Settings/account schema; no automatic group, membership or grants.

Revision ID: 20261115_0011
Revises: 20261114_0010
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '20261115_0011'
down_revision = '20261114_0010'
branch_labels = None
depends_on = None


def preflight(connection):
    rows = connection.execute(sa.text("SELECT id FROM users WHERE username IS NULL OR trim(username) = '' OR password_hash IS NULL OR trim(password_hash) = '' ORDER BY id")).scalars().all()
    return {'invalid_account_ids': list(rows), 'automatic_directors': 0, 'automatic_grants': 0}


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text('LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE'))
    if preflight(conn)['invalid_account_ids']:
        raise RuntimeError('Existing account identity/hash requires review; Settings migration aborted')
    op.create_table('access_state', sa.Column('id', sa.Integer(), primary_key=True), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('bootstrapped', sa.Boolean(), nullable=False), sa.CheckConstraint('id = 1', name='ck_access_state_singleton'), sa.CheckConstraint('revision >= 0', name='ck_access_revision_positive'))
    op.create_table('access_groups', sa.Column('id', sa.Integer(), primary_key=True), sa.Column('name', sa.String(120), nullable=False, unique=True), sa.Column('system_key', sa.String(32), unique=True), sa.Column('active', sa.Boolean(), nullable=False), sa.CheckConstraint("system_key IS NULL OR system_key = 'director'", name='ck_access_group_system'))
    op.create_table('access_memberships', sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), primary_key=True), sa.Column('group_id', sa.Integer(), sa.ForeignKey('access_groups.id', ondelete='RESTRICT'), primary_key=True), sa.Column('active', sa.Boolean(), nullable=False))
    op.create_table('access_grants', sa.Column('id', sa.Integer(), primary_key=True), sa.Column('group_id', sa.Integer(), sa.ForeignKey('access_groups.id', ondelete='RESTRICT'), nullable=False), sa.Column('capability', sa.String(120), nullable=False), sa.Column('branches', postgresql.JSONB(), nullable=False), sa.Column('ownership', sa.String(16), nullable=False), sa.Column('assignments', postgresql.JSONB(), nullable=False), sa.Column('active', sa.Boolean(), nullable=False), sa.UniqueConstraint('group_id', 'capability', 'branches', 'ownership', 'assignments', name='uq_access_grant_scope'), sa.CheckConstraint("ownership IN ('all', 'own', 'selected')", name='ck_access_grant_ownership'), sa.CheckConstraint("jsonb_typeof(branches) = 'array' AND jsonb_typeof(assignments) = 'array'", name='ck_access_grant_arrays'))
    op.create_index('ix_access_grants_group_id', 'access_grants', ['group_id'])
    op.create_table('access_audit', sa.Column('id', sa.Integer(), primary_key=True), sa.Column('revision', sa.Integer(), nullable=False, unique=True), sa.Column('actor_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False), sa.Column('action', sa.String(80), nullable=False), sa.Column('reason', sa.String(500), nullable=False), sa.Column('before', postgresql.JSONB(), nullable=False), sa.Column('after', postgresql.JSONB(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table('access_account_credentials', sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), primary_key=True), sa.Column('generation', sa.Integer(), nullable=False), sa.Column('must_change_password', sa.Boolean(), nullable=False), sa.CheckConstraint('generation >= 1', name='ck_account_generation'))
    conn.execute(sa.text('INSERT INTO access_state (id,revision,bootstrapped) VALUES (1,0,false)'))
    # Existing passwords are not replaced; new accounts use first-login change.
    conn.execute(sa.text('INSERT INTO access_account_credentials (user_id,generation,must_change_password) SELECT id,1,false FROM users'))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text('LOCK TABLE access_state, access_account_credentials, access_audit IN ACCESS EXCLUSIVE MODE'))
    if conn.scalar(sa.text('SELECT bootstrapped FROM access_state WHERE id=1')) or conn.scalar(sa.text('SELECT count(*) FROM access_audit')) or conn.scalar(sa.text('SELECT count(*) FROM access_account_credentials WHERE generation <> 1 OR must_change_password')):
        raise RuntimeError('Settings is in use; destructive downgrade would lose audit/session revocations')
    for table in ['access_account_credentials', 'access_audit', 'access_grants', 'access_memberships', 'access_groups', 'access_state']:
        op.drop_table(table)
