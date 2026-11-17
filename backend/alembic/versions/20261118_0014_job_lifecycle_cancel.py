"""Fase 1C soft-cancel lifecycle + active-SO partial UNIQUE.

Revision ID: 20261118_0014
Revises: 20261117_0013

Isolated test DB only until Director approves Live apply.
- Multiple cancelled jobs may share accurate_so_number.
- At most one active job per accurate_so_number (canonical SO identity).
- Historical rows are never deleted.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261118_0014"
down_revision = "20261117_0013"
branch_labels = None
depends_on = None

ACTIVE_SO_INDEX = "uq_production_jobs_active_so"
LEGACY_SO_UNIQUE = "production_jobs_accurate_so_number_key"


def upgrade():
    op.add_column(
        "production_jobs",
        sa.Column(
            "lifecycle_status",
            sa.String(16),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "production_jobs",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "production_jobs",
        sa.Column("cancelled_by_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "production_jobs",
        sa.Column("cancel_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "production_jobs",
        sa.Column("cancel_gate", sa.String(32), nullable=True),
    )
    op.create_index(
        "ix_production_jobs_lifecycle_status",
        "production_jobs",
        ["lifecycle_status"],
    )
    op.create_check_constraint(
        "ck_production_jobs_lifecycle_status",
        "production_jobs",
        "lifecycle_status IN ('active', 'cancelled')",
    )

    op.add_column(
        "job_line_qtys",
        sa.Column(
            "line_status",
            sa.String(32),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "job_line_qtys",
        sa.Column("revision_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "job_line_qtys",
        sa.Column("removed_from_source_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_job_line_qtys_line_status",
        "job_line_qtys",
        ["line_status"],
    )
    op.create_check_constraint(
        "ck_job_line_qtys_line_status",
        "job_line_qtys",
        "line_status IN ('active', 'removed_from_source', 'revision_conflict')",
    )

    conn = op.get_bind()
    # Existing rows become active; refuse upgrade if active SO duplicates appear
    # (should be impossible under the previous global UNIQUE).
    dup = conn.execute(
        sa.text(
            "SELECT accurate_so_number, count(*) AS n FROM production_jobs "
            "WHERE lifecycle_status = 'active' "
            "GROUP BY accurate_so_number HAVING count(*) > 1"
        )
    ).fetchall()
    if dup:
        raise RuntimeError(
            "Cannot create partial UNIQUE: duplicate active SO numbers already exist: "
            + ", ".join(f"{r[0]}×{r[1]}" for r in dup)
        )

    op.drop_constraint(LEGACY_SO_UNIQUE, "production_jobs", type_="unique")
    op.create_index(
        ACTIVE_SO_INDEX,
        "production_jobs",
        ["accurate_so_number"],
        unique=True,
        postgresql_where=sa.text("lifecycle_status = 'active'"),
    )


def downgrade():
    conn = op.get_bind()
    cancelled = conn.scalar(
        sa.text("SELECT count(*) FROM production_jobs WHERE lifecycle_status = 'cancelled'")
    )
    if cancelled:
        raise RuntimeError(
            "production_jobs has cancelled rows; restoring global UNIQUE would collide — "
            "destructive downgrade refused"
        )
    conflicted = conn.scalar(
        sa.text(
            "SELECT count(*) FROM job_line_qtys "
            "WHERE line_status <> 'active' OR revision_note IS NOT NULL "
            "OR removed_from_source_at IS NOT NULL"
        )
    )
    if conflicted:
        raise RuntimeError(
            "job_line_qtys has revision markers; destructive downgrade refused"
        )
    # Safe only when every job is still active and SO numbers remain unique.
    op.drop_index(ACTIVE_SO_INDEX, table_name="production_jobs")
    op.create_unique_constraint(
        LEGACY_SO_UNIQUE, "production_jobs", ["accurate_so_number"]
    )

    op.drop_constraint("ck_job_line_qtys_line_status", "job_line_qtys", type_="check")
    op.drop_index("ix_job_line_qtys_line_status", table_name="job_line_qtys")
    op.drop_column("job_line_qtys", "removed_from_source_at")
    op.drop_column("job_line_qtys", "revision_note")
    op.drop_column("job_line_qtys", "line_status")
    op.drop_constraint(
        "ck_production_jobs_lifecycle_status", "production_jobs", type_="check"
    )
    op.drop_index("ix_production_jobs_lifecycle_status", table_name="production_jobs")
    op.drop_column("production_jobs", "cancel_gate")
    op.drop_column("production_jobs", "cancel_reason")
    op.drop_column("production_jobs", "cancelled_by_user_id")
    op.drop_column("production_jobs", "cancelled_at")
    op.drop_column("production_jobs", "lifecycle_status")
