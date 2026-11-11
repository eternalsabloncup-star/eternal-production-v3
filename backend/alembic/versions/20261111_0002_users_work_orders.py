"""Users and work_orders for V3 auth + inbox status.

Revision ID: 20261111_0002
Revises: 20261111_0001
Create Date: 2026-11-11 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261111_0002"
down_revision: Union[str, None] = "20261111_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "branch_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "work_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("accurate_so_number", sa.String(length=120), nullable=False),
        sa.Column("accurate_id", sa.String(length=64), nullable=True),
        sa.Column("branch_id", sa.String(length=64), nullable=True),
        sa.Column(
            "processing_status",
            sa.String(length=16),
            nullable=False,
            server_default="Baru",
        ),
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
        sa.UniqueConstraint("accurate_so_number", name="uq_work_orders_so"),
    )
    op.create_index(
        "ix_work_orders_accurate_so_number", "work_orders", ["accurate_so_number"]
    )
    op.create_index("ix_work_orders_branch_id", "work_orders", ["branch_id"])


def downgrade() -> None:
    op.drop_index("ix_work_orders_branch_id", table_name="work_orders")
    op.drop_index("ix_work_orders_accurate_so_number", table_name="work_orders")
    op.drop_table("work_orders")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
