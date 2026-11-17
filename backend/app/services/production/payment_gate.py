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


_ACCURATE_STATUS_MAP = {
    "UNPAID": "Belum Bayar",
    "BELUM_BAYAR": "Belum Bayar",
    "BELUM BAYAR": "Belum Bayar",
    "PARTIAL": "Sebagian",
    "SEBAGIAN": "Sebagian",
    "PAID": "Lunas",
    "LUNAS": "Lunas",
    "FULLY_PAID": "Lunas",
}

# Proven payment evidence today: sales-receipt detail only (production gate).
# Invoice/AR outstanding is NOT on the Accurate gateway contract — fail closed.
_OUTSTANDING_ALLOWED_SOURCES = frozenset(
    {
        "accurate_receivable",
        "accurate_sales_invoice",
        "owner_verified_outstanding",
    }
)


def accurate_outstanding_contract() -> dict:
    """Declare Outstanding source availability — never invent an Accurate endpoint."""
    return {
        "status": "DIRECTOR_LIVE_EVIDENCE",
        "gateway_endpoint": "GET /sales-invoices[/{id}]",
        "upstream_accurate_path": "/accurate/api/sales-invoice/list.do|detail.do",
        "owing_field": "primeOwing",
        "docs_ref": (
            "Accurate OpenAPI sales-invoice list/detail; Director Live: primeOwing authoritative"
        ),
        "proven_payment_evidence": "GET /receipts/{id} → sales-receipt/detail.do",
        "production_gate": "local verified receipts / bypass (not invoice settlement)",
        "financial_payment_status_default": "UNKNOWN",
        # Director VPS Live list/detail PASS (sample 20). Gateway route deploy still separate.
        "live_verified": True,
        "live_sample_n": 20,
        "fail_closed": True,
        "note": (
            "Outstanding maps from verified Accurate sales-invoice primeOwing only "
            "(never totalAmount as sisa). Missing/invalid owing → UNKNOWN."
        ),
        "allowed_accurate_financial_sources": sorted(_OUTSTANDING_ALLOWED_SOURCES),
    }


def _owing_amount_valid(outstanding, invoice_total) -> bool:
    """Reject non-numeric / negative / NaN outstanding; totalAmount alone is never enough."""
    if outstanding is None:
        return False
    try:
        owing_f = float(outstanding)
    except (TypeError, ValueError):
        return False
    if owing_f != owing_f or owing_f < 0:  # NaN or negative
        return False
    if invoice_total is not None:
        try:
            total_f = float(invoice_total)
            if total_f != total_f or total_f < 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def map_accurate_financial_status(raw) -> str | None:
    """Map verified Accurate outstanding labels only — never invent from receipts."""
    if raw is None:
        return None
    key = str(raw).strip()
    if not key:
        return None
    if key in ("Belum Bayar", "Sebagian", "Lunas"):
        return key
    return _ACCURATE_STATUS_MAP.get(key.upper().replace("-", "_"))


def monitor_financial_fields(
    *,
    verified_amount,
    payment_status: str,
    accurate_financial: dict | None = None,
) -> dict:
    """Financial settlement from verified Accurate outstanding only; else UNKNOWN.

    Owner rule: follow Accurate/outstanding when verified; fallback UNKNOWN.
    Do not invent Belum Bayar / Sebagian / Lunas from local receipt sums alone.
    BR-F2-06R: invoice mutation behavior stays unchanged without a separate contract.
    """
    af = accurate_financial if isinstance(accurate_financial, dict) else {}
    verified = af.get("verified") is True
    source = str(af.get("source") or "").strip()
    mapped = map_accurate_financial_status(af.get("status") or af.get("financial_payment_status"))
    outstanding = af.get("outstanding_amount")
    invoice_total = af.get("invoice_total") or af.get("invoice_amount")
    owing_ok = _owing_amount_valid(outstanding, invoice_total)
    # Reject "settlement" that only echoes invoice total without an owing source key.
    owing_source = str(af.get("owing_source_key") or af.get("owing_field") or "").strip()
    if owing_source == "totalAmount":
        owing_ok = False
    # Fail-closed: verified + approved source + mapped label + valid primeOwing.
    if (
        verified
        and mapped
        and source in _OUTSTANDING_ALLOWED_SOURCES
        and owing_ok
    ):
        return {
            "production_approval_status": payment_status,
            "approval_source": approval_source_label(payment_status),
            "approved": payment_status in ("approved", "bypassed"),
            "financial_payment_status": mapped,
            "financial_receipt_state": financial_receipt_state(
                verified_amount=verified_amount, payment_status=payment_status
            ),
            "invoice_reference": af.get("invoice_reference"),
            "invoice_amount": invoice_total,
            "invoice_total": invoice_total,
            "outstanding_amount": outstanding,
            "remaining_amount": outstanding,
            "paid_amount": af.get("paid_amount", verified_amount),
            "financial_settlement_known": True,
            "financial_settlement_source": source,
            "owing_source_key": owing_source or "primeOwing",
            "financial_settlement_note": (
                "financial_payment_status dari Accurate primeOwing terverifikasi "
                f"({mapped}, source={source}); production gate tetap {payment_status}."
            ),
        }
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
            "Invoice outstanding / fully-paid settlement requires verified Accurate "
            "receivable payload; tanpa itu financial_payment_status=UNKNOWN "
            "(bukan Lunas palsu)."
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
