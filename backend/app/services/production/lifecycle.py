"""ProductionJob soft-cancel lifecycle + cancel gate (Fase 1C).

Does not mutate Accurate, stock, SJ, or POD. Cancelled jobs remain historically
queryable but are excluded from active Jadwal Produksi.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.production.event import ProductionEvent
from app.models.production.job import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_CANCELLED,
    LIFECYCLE_STATUSES,
    ProductionJob,
)
from app.models.production.operations import DeliveryPlan
from app.models.production.payment import PaymentBypass, PaymentReceiptRef
from app.models.production.prep import PrepState
from app.models.production.schedule import ScheduleAssignment
from app.models.user import User
from app.services.production.engine import _branch, get_job
from app.services.production.permissions import user_may_cancel_job

GATE_SAFE = "safe_auto"
GATE_REVIEW = "requires_review"
GATE_BLOCKED = "blocked"
GATE_DECISIONS = frozenset({GATE_SAFE, GATE_REVIEW, GATE_BLOCKED})

_PHYSICAL_BLOCK_EVENTS = frozenset(
    {
        "packing_batch",
        "packing_recorded",
        "loading",
        "loading_cancelled",
        "loading_return_requested",
        "loading_return_rejected",
        "pod",
        "sj_ref",
        "sj_cancelled",
    }
)
_PROGRESS_EVENTS = frozenset(
    {
        "output_confirmed",
        "output_correction",
        "output_helper_verified",
        "reject",
        "reject_verified",
    }
)


def assert_lifecycle(value: str | None) -> str:
    status = (value or LIFECYCLE_ACTIVE).strip().lower()
    if status not in LIFECYCLE_STATUSES:
        raise HTTPException(422, "lifecycle_status tidak valid")
    return status


def require_job_active(job: ProductionJob) -> None:
    if assert_lifecycle(job.lifecycle_status) == LIFECYCLE_CANCELLED:
        raise HTTPException(
            409,
            "ProductionJob sudah cancelled — aksi aktif ditolak; histori tetap tersedia",
        )


async def classify_cancel_gate(session: AsyncSession, job: ProductionJob) -> dict:
    """Classify cancel decision. Unknown/unsafe conditions default to BLOCKED."""
    reasons: list[str] = []
    blocked: list[str] = []
    review: list[str] = []

    asg_count = int(
        await session.scalar(
            select(func.count())
            .select_from(ScheduleAssignment)
            .where(
                ScheduleAssignment.job_id == job.id,
                ScheduleAssignment.status.in_(["active", "completed", "transferred"]),
            )
        )
        or 0
    )
    if asg_count:
        review.append(f"assignments={asg_count}")

    prep_qty = await session.scalar(
        select(func.coalesce(func.sum(PrepState.qty), 0)).where(PrepState.job_id == job.id)
    )
    if Decimal(prep_qty or 0) > 0:
        review.append("prep_activity")

    physical = int(
        await session.scalar(
            select(func.count())
            .select_from(ProductionEvent)
            .where(
                ProductionEvent.job_id == job.id,
                ProductionEvent.event_type.in_(sorted(_PHYSICAL_BLOCK_EVENTS)),
            )
        )
        or 0
    )
    if physical:
        blocked.append(f"physical_or_delivery_events={physical}")

    progress = int(
        await session.scalar(
            select(func.count())
            .select_from(ProductionEvent)
            .where(
                ProductionEvent.job_id == job.id,
                ProductionEvent.event_type.in_(sorted(_PROGRESS_EVENTS)),
            )
        )
        or 0
    )
    if progress:
        # Physical production progress cannot be auto-cancelled.
        blocked.append(f"production_progress_events={progress}")

    plans = int(
        await session.scalar(
            select(func.count()).select_from(DeliveryPlan).where(DeliveryPlan.job_id == job.id)
        )
        or 0
    )
    if plans:
        blocked.append(f"delivery_plans={plans}")

    receipts = int(
        await session.scalar(
            select(func.count())
            .select_from(PaymentReceiptRef)
            .where(
                PaymentReceiptRef.job_id == job.id,
                PaymentReceiptRef.status == "valid",
            )
        )
        or 0
    )
    if receipts:
        review.append(f"payment_receipts={receipts}")

    bypasses = int(
        await session.scalar(
            select(func.count())
            .select_from(PaymentBypass)
            .where(PaymentBypass.job_id == job.id, PaymentBypass.active.is_(True))
        )
        or 0
    )
    if bypasses:
        review.append(f"payment_bypass={bypasses}")

    if blocked:
        decision = GATE_BLOCKED
        reasons = blocked + review
    elif review:
        decision = GATE_REVIEW
        reasons = review
    else:
        decision = GATE_SAFE
        reasons = ["no_assignment_progress_receipt_or_delivery"]

    return {
        "job_id": job.id,
        "accurate_so_number": job.accurate_so_number,
        "lifecycle_status": assert_lifecycle(job.lifecycle_status),
        "decision": decision,
        "reasons": reasons,
        "can_cancel": decision in {GATE_SAFE, GATE_REVIEW},
        "requires_confirm_review": decision == GATE_REVIEW,
        "note": (
            "Default BLOCKED when physical/SJ/POD/progress dependency exists. "
            "Cancel never mutates Accurate, stock, SJ, or POD."
        ),
    }


async def cancel_job(
    session: AsyncSession,
    user: User,
    job_id: int,
    *,
    reason: str,
    idempotency_key: str,
    confirm_review: bool = False,
) -> dict:
    """Soft-cancel a ProductionJob. Idempotent on repeated cancel / idempotency key."""
    if not user_may_cancel_job(user):
        raise HTTPException(
            403,
            "Izin production.job.cancel tidak mencukupi (Direktur atau grant eksplisit)",
        )
    reason_s = (reason or "").strip()
    if len(reason_s) < 5:
        raise HTTPException(422, "Alasan cancel wajib (min 5 karakter)")
    key = (idempotency_key or "").strip()
    if len(key) < 8:
        raise HTTPException(422, "idempotency_key wajib")

    job = await get_job(session, job_id)
    _branch(user, job.branch_id)
    locked = await session.scalar(
        select(ProductionJob)
        .where(ProductionJob.id == job.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None:
        raise HTTPException(404, "Production job tidak ditemukan")
    _branch(user, locked.branch_id)

    prior = await session.scalar(
        select(ProductionEvent).where(ProductionEvent.idempotency_key == key)
    )
    if prior is not None:
        if prior.job_id != locked.id or prior.event_type != "job_cancelled":
            raise HTTPException(409, "Idempotency key dipakai untuk permintaan lain")
        return {
            "id": locked.id,
            "lifecycle_status": LIFECYCLE_CANCELLED,
            "replay": True,
            "event_id": prior.id,
            "cancel_gate": locked.cancel_gate,
            "cancelled_at": locked.cancelled_at.isoformat() if locked.cancelled_at else None,
            "cancel_reason": locked.cancel_reason,
        }

    if assert_lifecycle(locked.lifecycle_status) == LIFECYCLE_CANCELLED:
        # Idempotent repeat without matching key — surface current cancelled state.
        return {
            "id": locked.id,
            "lifecycle_status": LIFECYCLE_CANCELLED,
            "replay": True,
            "event_id": None,
            "cancel_gate": locked.cancel_gate,
            "cancelled_at": locked.cancelled_at.isoformat() if locked.cancelled_at else None,
            "cancel_reason": locked.cancel_reason,
            "note": "Job sudah cancelled sebelumnya",
        }

    gate = await classify_cancel_gate(session, locked)
    decision = gate["decision"]
    if decision == GATE_BLOCKED:
        raise AppError(
            "Cancel diblokir — ada dependency fisik/transaksi yang tidak aman",
            code="job_cancel_blocked",
            status_code=409,
            details={"cancel_gate": gate},
        )
    if decision == GATE_REVIEW and not confirm_review:
        raise AppError(
            "Cancel memerlukan konfirmasi review (confirm_review=true)",
            code="job_cancel_requires_review",
            status_code=409,
            details={"cancel_gate": gate},
        )

    now = datetime.now(UTC)
    locked.lifecycle_status = LIFECYCLE_CANCELLED
    locked.cancelled_at = now
    locked.cancelled_by_user_id = user.id
    locked.cancel_reason = reason_s
    locked.cancel_gate = decision

    ev = ProductionEvent(
        job_id=locked.id,
        event_type="job_cancelled",
        idempotency_key=key,
        actor_user_id=user.id,
        reason=reason_s,
        payload_json=json.dumps(
            {
                "cancel_gate": decision,
                "reasons": gate["reasons"],
                "confirm_review": bool(confirm_review),
            },
            ensure_ascii=False,
        ),
    )
    session.add(ev)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # Concurrent cancel with same key → replay; different outcome → conflict.
        again = await session.scalar(
            select(ProductionEvent).where(ProductionEvent.idempotency_key == key)
        )
        if again is not None and again.job_id == job_id and again.event_type == "job_cancelled":
            refreshed = await get_job(session, job_id)
            return {
                "id": refreshed.id,
                "lifecycle_status": LIFECYCLE_CANCELLED,
                "replay": True,
                "event_id": again.id,
                "cancel_gate": refreshed.cancel_gate,
                "cancelled_at": refreshed.cancelled_at.isoformat()
                if refreshed.cancelled_at
                else None,
                "cancel_reason": refreshed.cancel_reason,
            }
        raise HTTPException(409, "Cancel gagal karena konflik konkurensi") from exc

    await session.refresh(locked)
    return {
        "id": locked.id,
        "lifecycle_status": LIFECYCLE_CANCELLED,
        "replay": False,
        "event_id": ev.id,
        "cancel_gate": decision,
        "cancelled_at": locked.cancelled_at.isoformat() if locked.cancelled_at else None,
        "cancel_reason": locked.cancel_reason,
        "gate": gate,
    }
