"""Phase 2.1 screener/helper prep + operator payroll tables.

Revision ID: 20261111_0005
Revises: 20261111_0004
Create Date: 2026-11-11 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261111_0005"
down_revision: Union[str, None] = "20261111_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_line_qtys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("so_line_id", sa.String(length=120), nullable=False),
        sa.Column("po_qty", sa.Numeric(18, 3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["production_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "so_line_id", name="uq_job_line_qty"),
    )
    op.create_index("ix_job_line_qtys_job_id", "job_line_qtys", ["job_id"])

    op.create_table(
        "prep_states",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("so_line_id", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("qty", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("evidence_ref", sa.String(length=512), nullable=True),
        sa.Column("assignment_id", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["schedule_assignments.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["production_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id", "so_line_id", "role", name="uq_prep_state"
        ),
    )
    op.create_index("ix_prep_states_job_id", "prep_states", ["job_id"])

    op.create_table(
        "prep_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("so_line_id", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("qty_before", sa.Numeric(18, 3), nullable=False),
        sa.Column("qty_after", sa.Numeric(18, 3), nullable=False),
        sa.Column("assignment_id", sa.Integer(), nullable=True),
        sa.Column("evidence_ref", sa.String(length=512), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["schedule_assignments.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["production_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_prep_events_idempotency"),
    )
    op.create_index("ix_prep_events_job_id", "prep_events", ["job_id"])

    op.create_table(
        "operator_rates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("component", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operator_rates_component", "operator_rates", ["component"])

    op.create_table(
        "payroll_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("branch_id", sa.String(length=64), nullable=True),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="finalized"
        ),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("rate_snapshot_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_payroll_runs_idempotency"),
    )

    op.create_table(
        "payroll_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("operator_name", sa.String(length=120), nullable=False),
        sa.Column("branch_id", sa.String(length=64), nullable=False),
        sa.Column("qty_one", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("qty_two", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("qty_three", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("qty_four", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("qty_screen", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("amount_gross", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("source_event_ids", sa.Text(), nullable=False),
        sa.Column("rate_snapshot_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["payroll_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "operator_name", name="uq_payroll_line_operator"),
    )
    op.create_index("ix_payroll_lines_run_id", "payroll_lines", ["run_id"])


def downgrade() -> None:
    op.drop_table("payroll_lines")
    op.drop_table("payroll_runs")
    op.drop_table("operator_rates")
    op.drop_table("prep_events")
    op.drop_table("prep_states")
    op.drop_table("job_line_qtys")
