"""Phase 2 production workflow tables.

Revision ID: 20261111_0004
Revises: 20261111_0003
Create Date: 2026-11-11 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261111_0004"
down_revision: Union[str, None] = "20261111_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "production_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("accurate_so_number", sa.String(length=120), nullable=False),
        sa.Column("accurate_id", sa.String(length=64), nullable=True),
        sa.Column("branch_id", sa.String(length=64), nullable=False),
        sa.Column("customer_name", sa.String(length=200), nullable=True),
        sa.Column(
            "design_status", sa.String(length=32), nullable=False, server_default="pending"
        ),
        sa.Column(
            "payment_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "sample_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_required",
        ),
        sa.Column(
            "processing_status",
            sa.String(length=16),
            nullable=False,
            server_default="Baru",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("accurate_so_number"),
    )
    op.create_index(
        "ix_production_jobs_accurate_so_number",
        "production_jobs",
        ["accurate_so_number"],
    )
    op.create_index("ix_production_jobs_branch_id", "production_jobs", ["branch_id"])

    op.create_table(
        "design_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="pending"
        ),
        sa.Column("decision_by", sa.Integer(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "bypass", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "customer_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["production_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_design_versions_job_id", "design_versions", ["job_id"])

    op.create_table(
        "payment_receipt_refs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("accurate_receipt_id", sa.String(length=120), nullable=False),
        sa.Column("accurate_receipt_number", sa.String(length=120), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="valid"
        ),
        sa.Column("recorded_by", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["production_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_payment_receipt_refs_job_id", "payment_receipt_refs", ["job_id"]
    )

    op.create_table(
        "payment_bypasses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("authorized_by", sa.Integer(), nullable=False),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("revoked_by", sa.Integer(), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["production_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_bypasses_job_id", "payment_bypasses", ["job_id"])

    op.create_table(
        "schedule_assignments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("so_line_id", sa.String(length=120), nullable=False),
        sa.Column("product_id", sa.String(length=120), nullable=True),
        sa.Column("color_pass", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("operator_name", sa.String(length=120), nullable=False),
        sa.Column("machine_name", sa.String(length=120), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("branch_id", sa.String(length=64), nullable=False),
        sa.Column("qty_planned", sa.Numeric(18, 3), nullable=False),
        sa.Column(
            "qty_confirmed", sa.Numeric(18, 3), nullable=False, server_default="0"
        ),
        sa.Column(
            "qty_cancelled_remaining",
            sa.Numeric(18, 3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="active"
        ),
        sa.Column("transferred_to_id", sa.Integer(), nullable=True),
        sa.Column("location_provenance", sa.String(length=255), nullable=True),
        sa.Column("sequence_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["production_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "so_line_id",
            "color_pass",
            "operator_name",
            "machine_name",
            "work_date",
            "sequence_no",
            name="uq_schedule_assignment_identity",
        ),
    )
    op.create_index(
        "ix_schedule_assignments_job_id", "schedule_assignments", ["job_id"]
    )

    op.create_table(
        "sample_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("assignment_id", sa.Integer(), nullable=True),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="pending"
        ),
        sa.Column("decision_by", sa.Integer(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "required_before_print",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assignment_id"], ["schedule_assignments.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["production_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sample_versions_job_id", "sample_versions", ["job_id"])

    op.create_table(
        "production_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("assignment_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("so_line_id", sa.String(length=120), nullable=True),
        sa.Column("color_pass", sa.Integer(), nullable=True),
        sa.Column("lot_code", sa.String(length=120), nullable=True),
        sa.Column("qty_physical", sa.Numeric(18, 3), nullable=True),
        sa.Column("qty_pass_ops", sa.Numeric(18, 3), nullable=True),
        sa.Column("accurate_sj_id", sa.String(length=120), nullable=True),
        sa.Column("accurate_sj_number", sa.String(length=120), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence_ref", sa.String(length=512), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["schedule_assignments.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["production_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_production_events_idempotency"
        ),
    )
    op.create_index("ix_production_events_job_id", "production_events", ["job_id"])
    op.create_index(
        "ix_production_events_assignment_id", "production_events", ["assignment_id"]
    )
    op.create_index(
        "ix_production_events_event_type", "production_events", ["event_type"]
    )


def downgrade() -> None:
    op.drop_table("production_events")
    op.drop_table("sample_versions")
    op.drop_table("schedule_assignments")
    op.drop_table("payment_bypasses")
    op.drop_table("payment_receipt_refs")
    op.drop_table("design_versions")
    op.drop_table("production_jobs")
