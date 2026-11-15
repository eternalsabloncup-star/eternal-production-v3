"""Effective payment status from local verified evidence; never trust the mirror.

Reads do not write/commit or call Accurate. Revalidation is an explicit mutation.
A single SQL statement evaluates receipts and bypasses in the same snapshot.

Production-payment gate ≠ Accurate financial settlement:
- approved: ≥1 valid verified positive receipt (partial OR full unknown vs invoice)
- bypassed: active administrative bypass (does not change Accurate outstanding)
- pending: neither

Invoice amount / outstanding / fully-paid are NOT derived here — Accurate
receivable/invoice allocation is not an established V3 contract. Callers must
leave those fields null rather than invent balances.
"""
from __future__ import annotations

from sqlalchemy import case, exists, select
from app.models.production.job import ProductionJob
from app.models.production.payment import PaymentBypass, PaymentReceiptRef

# Local production progress that, after payment evidence loss, requires review.
_PROGRESS_EVENT_TYPES = frozenset(
    {
        "output_confirmed",
        "output_correction",
        "reject_recorded",
        "packing_recorded",
        "loading_confirmed",
        "pod_confirmed",
        "prep_screener",
        "prep_helper",
    }
)


def status_expression():
    receipt = exists().where(
        PaymentReceiptRef.job_id == ProductionJob.id,
        PaymentReceiptRef.status == "valid",
        PaymentReceiptRef.evidence_verified.is_(True),
        PaymentReceiptRef.amount > 0,
    )
    bypass = exists().where(
        PaymentBypass.job_id == ProductionJob.id,
        PaymentBypass.active.is_(True),
    )
    return case((receipt, "approved"), (bypass, "bypassed"), else_="pending")


async def effective_statuses(session, job_ids):
    if not job_ids:
        return {}
    rows = await session.execute(
        select(ProductionJob.id, status_expression()).where(ProductionJob.id.in_(job_ids))
    )
    return dict(rows.all())


async def effective_status(session, job_id):
    return (await effective_statuses(session, [job_id])).get(job_id, "pending")


def financial_receipt_state(*, verified_amount, payment_status: str) -> str:
    """Local receipt-derived label only — never claims invoice settlement."""
    if payment_status == "bypassed" and verified_amount is None:
        return "none_bypassed"
    if verified_amount is None:
        return "none"
    # Verified positive receipt(s) present; invoice remaining is unknown without
    # an Accurate receivable contract.
    return "verified_received"


def approval_source_label(payment_status: str) -> str:
    """Handoff approval_source — independent of financial Belum Bayar/Sebagian/Lunas."""
    if payment_status == "approved":
        return "Penerimaan"
    if payment_status == "bypassed":
        return "Bypass"
    return "Belum Approved"


def monitor_financial_fields(*, verified_amount, payment_status: str) -> dict:
    """Explicit nulls for unsupported Accurate financial fields.

    financial_payment_status stays UNKNOWN until Accurate receivable allocation is contracted.
    Do not invent Belum Bayar / Sebagian / Lunas from receipt sums alone.
    """
    return {
        "production_approval_status": payment_status,
        "approval_source": approval_source_label(payment_status),
        "approved": payment_status in ("approved", "bypassed"),
        "financial_payment_status": "UNKNOWN",
        "financial_receipt_state": financial_receipt_state(
            verified_amount=verified_amount, payment_status=payment_status
        ),
        # Not established in Accurate gateway contract for V3 — never invent.
        "invoice_reference": None,
        "invoice_amount": None,
        "invoice_total": None,
        "outstanding_amount": None,
        "remaining_amount": None,
        "paid_amount": verified_amount,
        "financial_settlement_known": False,
        "financial_settlement_note": (
            "Accurate sales-receipt evidence opens the production-payment gate. "
            "Invoice outstanding / fully-paid settlement is not mapped in V3; "
            "verified_amount is the sum of valid verified receipts only. "
            "financial_payment_status=UNKNOWN (bukan Lunas palsu)."
        ),
    }


async def job_has_production_progress(session, job_id: int) -> bool:
    from sqlalchemy import func
    from app.models.production.event import ProductionEvent

    count = await session.scalar(
        select(func.count())
        .select_from(ProductionEvent)
        .where(
            ProductionEvent.job_id == job_id,
            ProductionEvent.event_type.in_(sorted(_PROGRESS_EVENT_TYPES)),
        )
    )
    return int(count or 0) > 0
