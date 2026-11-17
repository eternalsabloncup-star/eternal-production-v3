"""Fase 3: Master Cabang PostgreSQL (production_branches).

Revision ID: 20261120_0017
Revises: 20261119_0016

Does not rewrite existing job/user/grant branch string IDs.
No automatic seed. Soft-deactivate only — no hard-delete of referenced rows.
Repository / isolated test DB only until Director approves Live apply.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261120_0017"
down_revision = "20261119_0016"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "production_branches",
        sa.Column("code", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accurate_branch_id", sa.String(length=64), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("zone", sa.String(length=64), nullable=True),
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
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_production_branches_active", "production_branches", ["active"])
    op.create_index("ix_production_branches_sort_order", "production_branches", ["sort_order"])

    op.create_table(
        "production_branches_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("branch_code", sa.String(length=64), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column(
            "before",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "after",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_production_branches_audit_branch_code",
        "production_branches_audit",
        ["branch_code"],
    )
    op.create_index(
        "ix_production_branches_audit_created_at",
        "production_branches_audit",
        ["created_at"],
    )


def downgrade():
    op.drop_index("ix_production_branches_audit_created_at", table_name="production_branches_audit")
    op.drop_index("ix_production_branches_audit_branch_code", table_name="production_branches_audit")
    op.drop_table("production_branches_audit")
    op.drop_index("ix_production_branches_sort_order", table_name="production_branches")
    op.drop_index("ix_production_branches_active", table_name="production_branches")
    op.drop_table("production_branches")
