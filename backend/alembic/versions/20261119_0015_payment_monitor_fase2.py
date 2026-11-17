"""Fase 2 payment monitor: paid_at, bypass idempotency, review flag.

Revision ID: 20261119_0015
Revises: 20261118_0014

Repository / isolated test DB only until Director approves Live apply.
No Accurate ledger mutation. No historical receipt rewrite.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261119_0015"
down_revision = "20261118_0014"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "payment_receipt_refs",
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payment_bypasses",
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "payment_bypasses",
        sa.Column("gate_before", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "uq_payment_bypass_request",
        "payment_bypasses",
        ["job_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.add_column(
        "production_jobs",
        sa.Column(
            "payment_review_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade():
    op.drop_column("production_jobs", "payment_review_required")
    op.drop_index("uq_payment_bypass_request", table_name="payment_bypasses")
    op.drop_column("payment_bypasses", "gate_before")
    op.drop_column("payment_bypasses", "idempotency_key")
    op.drop_column("payment_receipt_refs", "paid_at")
