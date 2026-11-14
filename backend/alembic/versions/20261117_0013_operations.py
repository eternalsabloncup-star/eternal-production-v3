"""Operator identity on assignments, machine master, delivery plan and history.

Revision ID: 20261117_0013
Revises: 20261116_0012
"""
from alembic import op
import sqlalchemy as sa

revision = '20261117_0013'
down_revision = '20261116_0012'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('job_line_qtys', sa.Column('source_qty', sa.Numeric(18, 3), nullable=True))
    op.add_column('job_line_qtys', sa.Column('drift_detected_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('schedule_assignments', sa.Column('operator_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=True))
    op.create_index('ix_schedule_assignments_operator_user_id', 'schedule_assignments', ['operator_user_id'])
    op.create_table('production_machines',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('branch_id', sa.String(64), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False, server_default='auto'),
        sa.Column('capacity_per_shift', sa.Numeric(18, 3), nullable=False),
        sa.Column('shifts_per_day', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('branch_id', 'name', name='uq_machine_branch_name'),
        sa.CheckConstraint("kind IN ('auto','semi_auto')", name='ck_machine_kind'),
        sa.CheckConstraint('capacity_per_shift > 0', name='ck_machine_capacity_positive'))
    op.create_index('ix_production_machines_branch_id', 'production_machines', ['branch_id'])
    op.create_table('delivery_plans',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('production_jobs.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('accurate_sj_id', sa.String(120), nullable=False),
        sa.Column('branch_id', sa.String(64), nullable=False),
        sa.Column('planned_date', sa.Date(), nullable=False),
        sa.Column('courier_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('job_id', 'accurate_sj_id', name='uq_delivery_plan_sj'))
    op.create_index('ix_delivery_plans_job_id', 'delivery_plans', ['job_id'])
    op.create_index('ix_delivery_plans_branch_id', 'delivery_plans', ['branch_id'])
    op.create_table('delivery_plan_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('plan_id', sa.Integer(), sa.ForeignKey('delivery_plans.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('production_jobs.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('previous_date', sa.Date()),
        sa.Column('new_date', sa.Date(), nullable=False),
        sa.Column('previous_courier_user_id', sa.Integer()),
        sa.Column('new_courier_user_id', sa.Integer()),
        sa.Column('reason', sa.Text()),
        sa.Column('idempotency_key', sa.String(120), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('job_id', 'idempotency_key', name='uq_delivery_plan_event_idem'))
    op.create_index('ix_delivery_plan_events_plan_id', 'delivery_plan_events', ['plan_id'])
    op.create_index('ix_delivery_plan_events_job_id', 'delivery_plan_events', ['job_id'])


def downgrade():
    conn = op.get_bind()
    for table in ('delivery_plan_events', 'delivery_plans', 'production_machines'):
        conn.execute(sa.text(f'LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE'))
        if conn.scalar(sa.text(f'SELECT count(*) FROM {table}')):
            raise RuntimeError(f'{table} has data; destructive downgrade refused')
    if conn.scalar(sa.text('SELECT count(*) FROM schedule_assignments WHERE operator_user_id IS NOT NULL')):
        raise RuntimeError('Operator identity recorded; destructive downgrade refused')
    if conn.scalar(sa.text('SELECT count(*) FROM job_line_qtys WHERE source_qty IS NOT NULL')):
        raise RuntimeError('Accurate qty drift recorded; destructive downgrade refused')
    op.drop_table('delivery_plan_events')
    op.drop_table('delivery_plans')
    op.drop_table('production_machines')
    op.drop_index('ix_schedule_assignments_operator_user_id', table_name='schedule_assignments')
    op.drop_column('schedule_assignments', 'operator_user_id')
    op.drop_column('job_line_qtys', 'drift_detected_at')
    op.drop_column('job_line_qtys', 'source_qty')
