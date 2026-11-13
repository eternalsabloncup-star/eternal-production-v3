"""Stable task ownership and delegation, without rewriting historical output."""
from alembic import op
import sqlalchemy as sa
revision='20261116_0012'
down_revision='20261115_0011'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('task_ownerships',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('job_id',sa.Integer(),sa.ForeignKey('production_jobs.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('assignment_id',sa.Integer(),sa.ForeignKey('schedule_assignments.id',ondelete='RESTRICT')),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('task_kind',sa.String(24),nullable=False),sa.Column('active',sa.Boolean(),nullable=False),
        sa.Column('delegated_from_id',sa.Integer(),sa.ForeignKey('task_ownerships.id',ondelete='RESTRICT')),
        sa.Column('expires_at',sa.DateTime(timezone=True)),
        sa.Column('created_by',sa.Integer(),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.CheckConstraint("task_kind IN ('screener','operator','helper','packing','loading','courier')",name='ck_task_ownership_kind'))
    for column in ('job_id','assignment_id','user_id'): op.create_index('ix_task_ownerships_'+column,'task_ownerships',[column])

def downgrade():
    conn=op.get_bind(); conn.execute(sa.text('LOCK TABLE task_ownerships IN ACCESS EXCLUSIVE MODE'))
    if conn.scalar(sa.text('SELECT count(*) FROM task_ownerships')): raise RuntimeError('Ownership history exists; destructive downgrade refused')
    op.drop_table('task_ownerships')
