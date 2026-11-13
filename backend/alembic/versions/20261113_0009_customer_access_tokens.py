"""P1-01 customer_access_tokens + design_versions.so_line_id.

Revision ID: 20261113_0009
Revises: 20261113_0008
Create Date: 2026-11-13

Additive / reversible. No data rewrite.
Apply ONLY to isolated disposable test PostgreSQL unless Owner
approves staging/ops. Never run against V3 Live / production without approval.

Default design-approval token TTL (runtime): V3_DESIGN_APPROVAL_TOKEN_TTL_HOURS=72
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261113_0009"
down_revision: Union[str, None] = "20261113_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "design_versions",
        sa.Column("so_line_id", sa.String(length=120), nullable=True),
    )
    op.create_table(
        "customer_access_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("design_version_id", sa.Integer(), nullable=True),
        sa.Column("so_line_id", sa.String(length=120), nullable=True),
        sa.Column("customer_slug", sa.String(length=120), nullable=False),
        sa.Column("po_slug", sa.String(length=120), nullable=False),
        sa.Column("branch_id", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["design_version_id"], ["design_versions.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["production_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_customer_access_tokens_token_hash",
        "customer_access_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_customer_access_tokens_scope",
        "customer_access_tokens",
        ["scope"],
        unique=False,
    )
    op.create_index(
        "ix_customer_access_tokens_job_id",
        "customer_access_tokens",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_customer_access_tokens_design_version_id",
        "customer_access_tokens",
        ["design_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_customer_tokens_job_scope_ver",
        "customer_access_tokens",
        ["job_id", "scope", "design_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_customer_tokens_job_scope_ver", table_name="customer_access_tokens")
    op.drop_index(
        "ix_customer_access_tokens_design_version_id",
        table_name="customer_access_tokens",
    )
    op.drop_index("ix_customer_access_tokens_job_id", table_name="customer_access_tokens")
    op.drop_index("ix_customer_access_tokens_scope", table_name="customer_access_tokens")
    op.drop_index(
        "ix_customer_access_tokens_token_hash", table_name="customer_access_tokens"
    )
    op.drop_table("customer_access_tokens")
    op.drop_column("design_versions", "so_line_id")
