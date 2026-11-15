"""Fase 3: versioned payment approval / bypass settings.

Revision ID: 20261119_0016
Revises: 20261119_0015

Repository / isolated test DB only until Director approves Live apply.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261119_0016"
down_revision = "20261119_0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment_approval_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_table(
        "payment_approval_settings_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("settings_version", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
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
        "ix_payment_approval_settings_audit_settings_version",
        "payment_approval_settings_audit",
        ["settings_version"],
    )


def downgrade():
    op.drop_index(
        "ix_payment_approval_settings_audit_settings_version",
        table_name="payment_approval_settings_audit",
    )
    op.drop_table("payment_approval_settings_audit")
    op.drop_table("payment_approval_settings")
