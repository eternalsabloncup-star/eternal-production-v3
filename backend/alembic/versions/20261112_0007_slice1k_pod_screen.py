"""Slice 1K: production_attachments + screener screen_size.

Revision ID: 20261112_0007
Revises: 20261112_0006
Create Date: 2026-11-12

Additive / reversible. Apply only to isolated test PostgreSQL unless Owner
approves staging/ops migration. Do not run against VPS without approval.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_0007"
down_revision: Union[str, None] = "20261112_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "production_attachments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("production_event_id", sa.Integer(), nullable=True),
        sa.Column("accurate_sj_id", sa.String(length=120), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["production_jobs.id"]),
        sa.ForeignKeyConstraint(["production_event_id"], ["production_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_production_attachments_storage_key"),
    )
    op.create_index(
        "ix_production_attachments_job_id", "production_attachments", ["job_id"]
    )
    op.create_index(
        "ix_production_attachments_production_event_id",
        "production_attachments",
        ["production_event_id"],
    )
    op.create_index(
        "ix_production_attachments_accurate_sj_id",
        "production_attachments",
        ["accurate_sj_id"],
    )
    op.create_index(
        "ix_production_attachments_branch_id",
        "production_attachments",
        ["branch_id"],
    )

    op.add_column(
        "prep_states",
        sa.Column("screen_size", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "prep_events",
        sa.Column("screen_size", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("prep_events", "screen_size")
    op.drop_column("prep_states", "screen_size")
    op.drop_index("ix_production_attachments_branch_id", table_name="production_attachments")
    op.drop_index(
        "ix_production_attachments_accurate_sj_id", table_name="production_attachments"
    )
    op.drop_index(
        "ix_production_attachments_production_event_id",
        table_name="production_attachments",
    )
    op.drop_index("ix_production_attachments_job_id", table_name="production_attachments")
    op.drop_table("production_attachments")
