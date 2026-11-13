"""P0 payment evidence provenance and idempotency; no historical data rewrite.

Revision ID: 20261114_0010
Revises: 20261113_0009
Existing receipts require re-verification before contributing to the gate.
Duplicate active references must be reviewed by Owner; migration refuses them.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261114_0010"
down_revision = "20261113_0009"
branch_labels = None
depends_on = None


def preflight(connection) -> dict:
    """Read-only inventory; no automatic deduplication or legacy verification."""
    duplicates = connection.execute(sa.text("""
        SELECT accurate_receipt_id, count(*) AS receipt_count,
               array_agg(id ORDER BY id) AS receipt_ids,
               array_agg(DISTINCT job_id ORDER BY job_id) AS job_ids
        FROM payment_receipt_refs WHERE status = 'valid'
        GROUP BY accurate_receipt_id HAVING count(*) > 1
        ORDER BY accurate_receipt_id
    """)).mappings().all()
    affected = connection.execute(sa.text("""
        SELECT DISTINCT job_id FROM payment_receipt_refs
        WHERE status = 'valid' ORDER BY job_id
    """)).scalars().all()
    invalid_ids = connection.execute(sa.text("""
        SELECT id FROM payment_receipt_refs WHERE status = 'valid'
        AND (accurate_receipt_id IS NULL OR trim(accurate_receipt_id) = '') ORDER BY id
    """)).scalars().all()
    return {"duplicate_active_receipts": [dict(row) for row in duplicates],
            "affected_job_ids": list(affected), "invalid_receipt_ids": list(invalid_ids),
            "legacy_evidence_verified": False}


def upgrade() -> None:
    connection = op.get_bind()
    # Prevent inserts/updates between preflight and unique-index creation.
    connection.execute(sa.text("LOCK TABLE payment_receipt_refs IN SHARE ROW EXCLUSIVE MODE"))
    report = preflight(connection)
    if report["duplicate_active_receipts"] or report["invalid_receipt_ids"]:
        raise RuntimeError("Duplicate active receipt evidence requires Owner review or invalid receipt identity; no rows changed")
    op.add_column("payment_receipt_refs", sa.Column("idempotency_key", sa.String(120)))
    op.add_column("payment_receipt_refs", sa.Column(
        "evidence_verified", sa.Boolean(), nullable=False, server_default=sa.false()
    ))
    op.create_index("uq_payment_receipt_active", "payment_receipt_refs",
                    ["accurate_receipt_id"], unique=True,
                    postgresql_where=sa.text("status = 'valid'"))
    op.create_index("uq_payment_receipt_request", "payment_receipt_refs",
                    ["job_id", "idempotency_key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_payment_receipt_request", table_name="payment_receipt_refs")
    op.drop_index("uq_payment_receipt_active", table_name="payment_receipt_refs")
    op.drop_column("payment_receipt_refs", "evidence_verified")
    op.drop_column("payment_receipt_refs", "idempotency_key")
