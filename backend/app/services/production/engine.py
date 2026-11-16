"""Single canonical workflow engine for Production V3."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.production.attachment import ProductionAttachment  # noqa: F401
from app.models.production.design import DesignVersion
from app.models.production.event import ProductionEvent
from app.models.production.job import ProductionJob
from app.models.production.payment import PaymentBypass, PaymentReceiptRef
from app.models.production.sample import SampleVersion
from app.models.production.schedule import ScheduleAssignment
from app.models.user import User
from app.models.work_order import WorkOrder
from app.services.production import permissions as P

# Canonical ledger event contracts (producers write the first name; consumers accept aliases).
CANONICAL_PACKING_EVENT = "packing_batch"
PACKING_EVENT_TYPES = frozenset({"packing_batch", "packing_recorded"})
OUTPUT_EVENT_TYPES = frozenset({"output_confirmed", "output_correction"})
HELPER_VERIFIED_EVENT = "output_helper_verified"
HELPER_VERIFIED_EVENT_TYPES = frozenset({HELPER_VERIFIED_EVENT})
REJECT_EVENT_TYPES = frozenset({"reject_verified"})
# Color pass 1 records cups entering print; later passes are work-ops on the same cups.
# Packing eligibility = helper-verified qty across ALL required passes (min), not operator alone.
PHYSICAL_CUP_COLOR_PASS = 1
_CANCELLED_ASSIGNMENT = frozenset({"cancelled", "canceled", "void", "cancelled_remaining"})


def _require(user: User, *perms: str) -> None:
    from app.authorization.workflow import legacy_allowed
    if not legacy_allowed(user, perms):
        raise HTTPException(403, "Izin tidak mencukupi")


def _branch(user: User, branch_id: str) -> None:
    from app.authorization.workflow import branch_allowed
    if not branch_allowed(user, branch_id):
        raise HTTPException(403, "Cabang di luar lingkup akses")


async def get_job(session: AsyncSession, job_id: int) -> ProductionJob:
    job = await session.get(ProductionJob, job_id)
    if job is None:
        raise HTTPException(404, "Production job tidak ditemukan")
    return job


def _event_color_pass(event) -> int:
    pass_no = getattr(event, "color_pass", None)
    if pass_no is None:
        return PHYSICAL_CUP_COLOR_PASS
    return int(pass_no)


def required_color_passes_from_assignments(
    assignments: list,
    *,
    so_line_id: str | None = None,
) -> frozenset[int]:
    """Required print passes for a line from schedule evidence (not assumed single-color)."""
    passes: set[int] = set()
    for a in assignments:
        status = str(getattr(a, "status", "active") or "active")
        if status in _CANCELLED_ASSIGNMENT:
            continue
        line = getattr(a, "so_line_id", None)
        if so_line_id is not None and line != so_line_id:
            continue
        passes.add(int(getattr(a, "color_pass", None) or PHYSICAL_CUP_COLOR_PASS))
    return frozenset(passes) if passes else frozenset({PHYSICAL_CUP_COLOR_PASS})


def qty_for_color_pass_from_events(
    events: list,
    color_pass: int,
    *,
    so_line_id: str | None = None,
) -> Decimal:
    """Net qty for one color pass: outputs + corrections − verified rejects."""
    total = Decimal("0")
    target = int(color_pass)
    for e in events:
        line = getattr(e, "so_line_id", None)
        if so_line_id is not None and line != so_line_id:
            continue
        if _event_color_pass(e) != target:
            continue
        et = getattr(e, "event_type", None)
        qty = Decimal(getattr(e, "qty_physical", 0) or 0)
        if et in OUTPUT_EVENT_TYPES:
            total += qty
        elif et in REJECT_EVENT_TYPES:
            total -= qty
    return total


def eligible_finished_qty_from_events(
    events: list,
    required_passes: frozenset[int] | set[int] | list[int],
    *,
    so_line_id: str | None = None,
) -> Decimal:
    """Operator net finished through ALL required color passes — never sum passes.

    Historical helper for operator progress. Packing authority uses
    ``eligible_verified_qty_from_events`` (helper-verified pool).
    """
    passes = frozenset(int(p) for p in required_passes) or frozenset(
        {PHYSICAL_CUP_COLOR_PASS}
    )
    return min(
        qty_for_color_pass_from_events(events, p, so_line_id=so_line_id) for p in passes
    )


def qty_helper_verified_for_pass_from_events(
    events: list,
    color_pass: int,
    *,
    so_line_id: str | None = None,
) -> Decimal:
    """Sum helper-verified qty for one color pass (rejects reduce the pool)."""
    target = int(color_pass)
    total = Decimal("0")
    for e in events:
        line = getattr(e, "so_line_id", None)
        if so_line_id is not None and line != so_line_id:
            continue
        if _event_color_pass(e) != target:
            continue
        et = getattr(e, "event_type", None)
        qty = Decimal(getattr(e, "qty_physical", 0) or 0)
        if et in HELPER_VERIFIED_EVENT_TYPES:
            total += qty
        elif et in REJECT_EVENT_TYPES:
            total -= qty
    return total


def eligible_verified_qty_from_events(
    events: list,
    required_passes: frozenset[int] | set[int] | list[int],
    *,
    so_line_id: str | None = None,
) -> Decimal:
    """Packable cups = min(helper-verified net per required pass). Never sum passes."""
    passes = frozenset(int(p) for p in required_passes) or frozenset(
        {PHYSICAL_CUP_COLOR_PASS}
    )
    return min(
        qty_helper_verified_for_pass_from_events(events, p, so_line_id=so_line_id)
        for p in passes
    )


def physical_cup_qty_from_events(
    events: list,
    *,
    so_line_id: str | None = None,
) -> Decimal:
    """Cups that entered print (color_pass 1 ledger) — not packing eligibility.

    Higher color_pass values are operator work-ops on the same cups and must not
    inflate this total. For packable finished qty use eligible_finished_qty_from_events.
    """
    return qty_for_color_pass_from_events(
        events, PHYSICAL_CUP_COLOR_PASS, so_line_id=so_line_id
    )


def packing_qty_from_events(
    events: list,
    *,
    so_line_id: str | None = None,
) -> Decimal:
    """Sum packing evidence — accepts canonical packing_batch and alias packing_recorded."""
    total = Decimal("0")
    for e in events:
        if getattr(e, "event_type", None) not in PACKING_EVENT_TYPES:
            continue
        line = getattr(e, "so_line_id", None)
        if so_line_id is not None and line != so_line_id:
            continue
        total += Decimal(getattr(e, "qty_physical", 0) or 0)
    return total


def _coerce_buffer_stock(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return None


def _coerce_urgent_state(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if not normalized:
        return None
    allowed = {
        "normal",
        "pending_request",
        "approved_urgent",
        "legacy_urgent",
    }
    if normalized in allowed:
        return normalized
    return None


async def find_active_job_by_so(
    session: AsyncSession, accurate_so_number: str
) -> ProductionJob | None:
    """Return the single active job for an SO, if any (never cancelled history)."""
    from app.models.production.job import LIFECYCLE_ACTIVE

    return await session.scalar(
        select(ProductionJob).where(
            ProductionJob.accurate_so_number == accurate_so_number,
            ProductionJob.lifecycle_status == LIFECYCLE_ACTIVE,
        )
    )


async def ensure_job(
    session: AsyncSession,
    user: User,
    *,
    accurate_so_number: str,
    branch_id: str,
    accurate_id: str | None = None,
    customer_name: str | None = None,
    buffer_stock: bool | None = None,
    urgent_state: str | None = None,
    line_items: list[dict] | None = None,
    commit: bool = True,
) -> ProductionJob:
    """Create or refresh the active job. Classifications stay null/unknown unless explicit.

    commit=False leaves the write pending in the caller's transaction (bulk sync).
    Cancelled jobs are never reactivated. Re-input after cancel creates a distinct
    active job; cancelled history stays queryable by job id.
    """
    from app.models.production.job import LIFECYCLE_ACTIVE
    from app.services.production.prep import sync_job_lines_from_so_detail

    _require(user, P.JOB_CREATE)
    _branch(user, branch_id)
    buffer_v = _coerce_buffer_stock(buffer_stock)
    urgent_v = _coerce_urgent_state(urgent_state)
    existing = await find_active_job_by_so(session, accurate_so_number)
    if existing:
        _branch(user, existing.branch_id)
        if accurate_id and not existing.accurate_id:
            existing.accurate_id = accurate_id
        if customer_name and not existing.customer_name:
            existing.customer_name = customer_name
        # Idempotent re-sync: None arg = leave unknown; never invent false.
        if buffer_stock is not None:
            existing.buffer_stock = buffer_v
        if urgent_state is not None:
            existing.urgent_state = urgent_v
        if line_items is not None:
            await sync_job_lines_from_so_detail(session, existing, line_items)
        if not commit:
            await session.flush()
            return existing
        await session.commit()
        await session.refresh(existing)
        return existing
    job = ProductionJob(
        accurate_so_number=accurate_so_number,
        accurate_id=accurate_id,
        branch_id=branch_id,
        customer_name=customer_name,
        buffer_stock=buffer_v,
        urgent_state=urgent_v,
        processing_status="Baru",
        lifecycle_status=LIFECYCLE_ACTIVE,
    )
    try:
        async with session.begin_nested():
            session.add(job)
            await session.flush()
    except IntegrityError:
        # Concurrent re-input raced on partial UNIQUE — adopt the winner.
        winner = await find_active_job_by_so(session, accurate_so_number)
        if winner is None:
            raise HTTPException(409, "Konflik re-input SO — coba ulang")
        _branch(user, winner.branch_id)
        if line_items is not None:
            await sync_job_lines_from_so_detail(session, winner, line_items)
        if not commit:
            await session.flush()
            return winner
        await session.commit()
        await session.refresh(winner)
        return winner
    if line_items:
        await sync_job_lines_from_so_detail(session, job, line_items)
    # Keep inbox WO mirror in sync (one WO per SO number — not lifecycle-scoped).
    wo = await session.scalar(
        select(WorkOrder).where(WorkOrder.accurate_so_number == accurate_so_number)
    )
    if wo is None:
        session.add(
            WorkOrder(
                accurate_so_number=accurate_so_number,
                accurate_id=accurate_id,
                branch_id=branch_id,
                processing_status="Baru",
            )
        )
    if not commit:
        await session.flush()
        return job
    await session.commit()
    await session.refresh(job)
    return job


async def _mark_terproses(session: AsyncSession, job: ProductionJob) -> None:
    if job.processing_status != "Terproses":
        job.processing_status = "Terproses"
        wo = await session.scalar(
            select(WorkOrder).where(
                WorkOrder.accurate_so_number == job.accurate_so_number
            )
        )
        if wo:
            wo.processing_status = "Terproses"


async def job_needs_design_gate(
    session: AsyncSession | None, job: ProductionJob
) -> bool:
    """Design gate applies to print (or unclassified) jobs — not non-print-only."""
    if session is None:
        return True
    from app.models.production.prep import JobLineQty

    lines = (
        await session.scalars(
            select(JobLineQty).where(JobLineQty.job_id == job.id)
        )
    ).all()
    if not lines:
        # Fail closed: unknown lines still require design before schedule/prep.
        return True
    has_print = any((ln.production_process or "") == "print" for ln in lines)
    has_non_print = any((ln.production_process or "") == "non_print" for ln in lines)
    if has_non_print and not has_print:
        return False
    return True


async def gates_open_for_schedule(
    job: ProductionJob, session: AsyncSession | None = None
) -> None:
    from app.services.production.lifecycle import require_job_active

    require_job_active(job)
    needs_design = await job_needs_design_gate(session, job)
    if needs_design:
        if job.design_status == "bypassed":
            pass
        elif job.design_status == "approved":
            # Strict: approved must reflect customer token approval of current revision
            # (or historical bypass already handled). Staff-only flags are insufficient.
            if session is not None:
                from app.services.production.customer_tokens import (
                    current_design_customer_approved,
                )

                if not await current_design_customer_approved(session, job):
                    raise HTTPException(
                        409,
                        "Design memerlukan persetujuan pelanggan pada revisi terkini",
                    )
        else:
            raise HTTPException(409, "Design belum disetujui/bypass")
    from app.services.production.payment_gate import effective_status
    if session is None or await effective_status(session, job.id) not in {"approved", "bypassed"}:
        raise HTTPException(409, "Payment belum disetujui/bypass")


async def _lock_payment_job(session: AsyncSession, user: User, job: ProductionJob) -> ProductionJob:
    """Serialize gate mutations and schedule creation; refresh identity-map state."""
    _branch(user, job.branch_id)
    locked = await session.scalar(
        select(ProductionJob).where(ProductionJob.id == job.id)
        .with_for_update().execution_options(populate_existing=True)
    )
    if locked is None:
        raise HTTPException(404, "Production job tidak ditemukan")
    _branch(user, locked.branch_id)
    return locked


async def _refresh_payment_gate(session: AsyncSession, job: ProductionJob) -> None:
    from app.services.production.payment_gate import effective_status
    job.payment_status = await effective_status(session, job.id)


# ---- Design ----


async def upload_design(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    file_name: str,
    storage_key: str,
    so_line_id: str | None = None,
) -> DesignVersion:
    _require(user, P.DESIGN_UPLOAD)
    _branch(user, job.branch_id)
    max_v = await session.scalar(
        select(func.coalesce(func.max(DesignVersion.version_no), 0)).where(
            DesignVersion.job_id == job.id
        )
    )
    # New upload supersedes prior pending/approved for gate until re-approved.
    prior = (
        await session.scalars(
            select(DesignVersion).where(
                DesignVersion.job_id == job.id,
                DesignVersion.status.in_(["pending", "approved"]),
            )
        )
    ).all()
    for row in prior:
        if row.status == "approved":
            row.status = "superseded"
            row.customer_approval = False
            job.design_status = "pending"
        elif row.status == "pending":
            row.status = "superseded"
    from app.services.production.customer_tokens import revoke_design_tokens_for_job

    await revoke_design_tokens_for_job(session, job.id)
    ver = DesignVersion(
        job_id=job.id,
        version_no=int(max_v or 0) + 1,
        file_name=file_name,
        storage_key=storage_key,
        so_line_id=(so_line_id or "").strip() or None,
        uploaded_by=user.id,
        status="pending",
    )
    session.add(ver)
    await _mark_terproses(session, job)
    await session.commit()
    await session.refresh(ver)
    return ver


async def decide_design(
    session: AsyncSession,
    user: User,
    version_id: int,
    *,
    decision: str,
    reason: str | None = None,
    bypass: bool = False,
    customer_approval: bool = False,
) -> DesignVersion:
    """Staff design decision.

    Strict printed-item gate: staff ``approved`` alone does **not** open schedule.
    Only customer ``design_approval`` token decision (or staff bypass) opens the gate.
    ``customer_approval`` body flag is ignored for gate authority (evidence-only legacy).
    """
    ver = await session.get(DesignVersion, version_id)
    if ver is None:
        raise HTTPException(404, "Design version tidak ditemukan")
    job = await get_job(session, ver.job_id)
    _branch(user, job.branch_id)
    if bypass:
        _require(user, P.DESIGN_BYPASS)
        if not reason:
            raise HTTPException(422, "Bypass design memerlukan alasan")
    else:
        _require(user, P.DESIGN_APPROVE)
    if decision not in {"approved", "rejected"}:
        raise HTTPException(422, "Keputusan design tidak valid")
    if ver.status not in {"pending", "approved"}:
        raise HTTPException(409, "Versi design tidak dapat diputuskan")
    ver.decision_by = user.id
    ver.decision_reason = reason
    ver.decided_at = datetime.now(UTC)
    if bypass:
        ver.status = "approved"
        ver.bypass = True
        # Bypass is staff-authorized gate open — not a customer legal claim.
        ver.customer_approval = False
        job.design_status = "bypassed"
    elif decision == "rejected":
        ver.status = "rejected"
        ver.bypass = False
        ver.customer_approval = False
        job.design_status = "rejected"
    else:
        # Staff internal OK — gate stays closed until customer token approves.
        ver.status = "approved"
        ver.bypass = False
        # Do not honor staff-set customer_approval as gate authority.
        _ = customer_approval
        if not ver.customer_approval:
            job.design_status = "pending"
        else:
            job.design_status = "approved"
    await session.commit()
    await session.refresh(ver)
    return ver


# ---- Payment ----


def _parse_paid_at(raw) -> datetime | None:
    """Parse Accurate paid_at when present; never invent a timestamp."""
    if raw in (None, ""):
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    text = str(raw).strip()
    if not text:
        return None
    try:
        # Support date-only Accurate transDate and ISO datetimes.
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            text = text + "T00:00:00+00:00"
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _maybe_clear_payment_review(session: AsyncSession, job: ProductionJob) -> None:
    """Clear review flag only when verified evidence or active bypass reopens the gate."""
    from app.services.production.payment_gate import effective_status

    if job.payment_review_required and await effective_status(session, job.id) in {
        "approved",
        "bypassed",
    }:
        job.payment_review_required = False


async def revalidate_receipt(session, user, receipt_id, *, reason, idempotency_key):
    """Explicit, fail-closed verification; never revive invalidated evidence."""
    import hashlib
    _require(user, P.PAYMENT_RECORD)
    if not reason.strip() or not 8 <= len(idempotency_key) <= 120:
        raise HTTPException(422, "Alasan dan idempotency key wajib")
    row = await session.get(PaymentReceiptRef, receipt_id)
    if row is None:
        raise HTTPException(404, "Receipt tidak ditemukan")
    job = await _lock_payment_job(session, user, await get_job(session, row.job_id))
    await session.refresh(row)
    key = "pay-revalidate:" + hashlib.sha256(idempotency_key.encode()).hexdigest()
    prior = await session.scalar(select(ProductionEvent).where(ProductionEvent.idempotency_key == key))
    if prior is not None:
        result = json.loads(prior.payload_json)
        if prior.job_id != job.id or result["receipt_id"] != row.id or prior.reason != reason.strip():
            raise HTTPException(409, "Idempotency key dipakai untuk request berbeda")
        from app.services.production.payment_gate import effective_status
        active = row.status == "valid" and row.evidence_verified and row.amount is not None and row.amount > 0
        return {**result, "verified": bool(active),
                "verification_error": result.get("verification_error") if active or not result["verified"] else "evidence_no_longer_active",
                "payment_status": await effective_status(session, job.id), "replayed": True}
    if row.status != "valid":
        raise HTTPException(409, "Receipt invalidated/reversed tidak dapat diaktifkan ulang")
    before = {"verified": row.evidence_verified, "amount": str(row.amount)}
    result = {"receipt_id": row.id, "verified": False, "verification_error": None}
    from app.services.accurate_evidence import require_valid_receipt
    try:
        if not job.accurate_id:
            raise HTTPException(409, "Identitas SO resmi belum tersedia")
        evidence = await require_valid_receipt(row.accurate_receipt_id,
            expected_so_number=job.accurate_so_number, expected_so_id=job.accurate_id,
            expected_branch_id=job.branch_id)
        if evidence["accurate_receipt_id"] != row.accurate_receipt_id:
            raise HTTPException(409, "Identitas receipt berubah; perlu review")
    except HTTPException as exc:
        row.evidence_verified = False
        result["verification_error"] = "source_unavailable" if exc.status_code >= 500 else "evidence_rejected"
    else:
        row.evidence_verified = True
        row.amount = evidence["amount"]
        row.accurate_receipt_number = evidence.get("accurate_receipt_number")
        paid = _parse_paid_at(evidence.get("paid_at"))
        if paid is not None:
            row.paid_at = paid
        result.update(verified=True, amount=str(row.amount), live_verified=evidence["live_verified"],
                      source=evidence.get("source"), payload_status=evidence["payload_status"],
                      paid_at=row.paid_at.isoformat() if row.paid_at else None)
    await session.flush()
    await _refresh_payment_gate(session, job)
    await _maybe_clear_payment_review(session, job)
    result.update(payment_status=job.payment_status, before=before,
                  payment_review_required=bool(job.payment_review_required))
    session.add(ProductionEvent(job_id=job.id, event_type="payment_receipt_revalidated",
        actor_user_id=user.id, idempotency_key=key, reason=reason.strip(), payload_json=json.dumps(result)))
    await session.commit()
    return result


async def record_payment_receipt(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    accurate_receipt_id: str,
    accurate_receipt_number: str | None = None,
    amount: Decimal | None = None,
    note: str | None = None,
    idempotency_key: str | None = None,
) -> PaymentReceiptRef:
    """Record verified gateway evidence; legacy amount/number inputs are ignored."""
    _require(user, P.PAYMENT_RECORD)
    job = await _lock_payment_job(session, user, job)
    if idempotency_key is not None and not 8 <= len(idempotency_key.strip()) <= 120:
        raise HTTPException(422, "Idempotency key tidak valid")
    idempotency_key = idempotency_key.strip() if idempotency_key else None
    if not job.accurate_id:
        raise HTTPException(409, "Identitas resmi SO belum tersedia untuk verifikasi receipt")
    from app.services.accurate_evidence import require_valid_receipt

    evidence = await require_valid_receipt(
        accurate_receipt_id,
        expected_so_number=job.accurate_so_number,
        expected_branch_id=job.branch_id,
        expected_so_id=job.accurate_id,
    )
    rid = evidence["accurate_receipt_id"]
    existing = None
    if idempotency_key:
        existing = await session.scalar(select(PaymentReceiptRef).where(
            PaymentReceiptRef.job_id == job.id,
            PaymentReceiptRef.idempotency_key == idempotency_key,
        ))
        if existing is not None and existing.accurate_receipt_id != rid:
            raise HTTPException(409, "Idempotency key dipakai untuk receipt berbeda")
    if existing is None:
        existing = await session.scalar(select(PaymentReceiptRef).where(
            PaymentReceiptRef.accurate_receipt_id == rid,
            PaymentReceiptRef.status == "valid",
        ))
    if existing is not None:
        if existing.job_id != job.id:
            raise HTTPException(409, "Receipt sudah terhubung ke job lain")
        if idempotency_key and existing.idempotency_key not in {None, idempotency_key}:
            raise HTTPException(409, "Receipt sudah memiliki idempotency key berbeda")
        if idempotency_key and existing.idempotency_key is None:
            existing.idempotency_key = idempotency_key
        paid = _parse_paid_at(evidence.get("paid_at"))
        if existing.status == "valid" and not existing.evidence_verified:
            existing.amount = evidence["amount"]
            existing.evidence_verified = True
            if paid is not None:
                existing.paid_at = paid
            session.add(ProductionEvent(
                job_id=job.id, event_type="payment_receipt_reverified",
                idempotency_key=f"pay-reverified:{existing.id}", actor_user_id=user.id,
                payload_json=json.dumps({"receipt_id": existing.id}),
            ))
        elif existing.status == "valid" and paid is not None and existing.paid_at is None:
            existing.paid_at = paid
        await session.flush()
        # Do not revive invalidated evidence on an idempotent replay.
        await _refresh_payment_gate(session, job)
        await _maybe_clear_payment_review(session, job)
        await session.commit()
        return existing
    row = PaymentReceiptRef(
        job_id=job.id, accurate_receipt_id=rid,
        accurate_receipt_number=evidence.get("accurate_receipt_number"),
        amount=evidence["amount"], evidence_verified=True,
        paid_at=_parse_paid_at(evidence.get("paid_at")),
        idempotency_key=idempotency_key, status="valid", recorded_by=user.id,
        note=(note or "") + f" | evidence:{evidence['mode']}:{evidence['payload_status']}",
    )
    session.add(row)
    try:
        await session.flush()
        await _refresh_payment_gate(session, job)
        await _maybe_clear_payment_review(session, job)
        await _mark_terproses(session, job)
        session.add(ProductionEvent(
            job_id=job.id, event_type="payment_receipt_verified",
            idempotency_key=f"pay-receipt:{row.id}", actor_user_id=user.id,
            payload_json=json.dumps({"receipt_id": row.id, "accurate_receipt_id": rid,
                                     "amount": str(row.amount),
                                     "paid_at": row.paid_at.isoformat() if row.paid_at else None}),
        ))
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Receipt / idempotency key sudah digunakan") from exc
    await session.refresh(row)
    return row


async def bypass_payment(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    reason: str,
    idempotency_key: str | None = None,
) -> PaymentBypass:
    # Direktur default mirrors job.cancel — never trust client-supplied role/perms.
    if not P.user_may_bypass_payment(user):
        raise HTTPException(
            403,
            "Izin production.payment.bypass tidak mencukupi (Direktur atau grant eksplisit)",
        )
    from app.services.production.payment_settings import bypass_enabled as settings_bypass_enabled

    if not await settings_bypass_enabled(session):
        raise HTTPException(
            403,
            "Bypass payment dinonaktifkan di Pengaturan Approval Payment",
        )
    job = await _lock_payment_job(session, user, job)
    if not reason.strip():
        raise HTTPException(422, "Bypass payment memerlukan alasan")
    key = idempotency_key.strip() if idempotency_key else None
    if key is not None and not 8 <= len(key) <= 120:
        raise HTTPException(422, "Idempotency key tidak valid")
    from app.services.production.payment_gate import effective_status

    gate_before = await effective_status(session, job.id)
    if key:
        existing = await session.scalar(
            select(PaymentBypass).where(
                PaymentBypass.job_id == job.id,
                PaymentBypass.idempotency_key == key,
            )
        )
        if existing is not None:
            if existing.reason != reason.strip():
                raise HTTPException(409, "Idempotency key dipakai untuk alasan bypass berbeda")
            await _refresh_payment_gate(session, job)
            await _maybe_clear_payment_review(session, job)
            await session.commit()
            return existing
    row = PaymentBypass(
        job_id=job.id,
        reason=reason.strip(),
        authorized_by=user.id,
        idempotency_key=key,
        gate_before=gate_before,
        active=True,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Idempotency key bypass sudah digunakan") from exc
    await _refresh_payment_gate(session, job)
    await _maybe_clear_payment_review(session, job)
    await _mark_terproses(session, job)
    event_key = key or (
        f"pay-bypass:{job.id}:{user.id}:"
        f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
    )
    session.add(
        ProductionEvent(
            job_id=job.id,
            event_type="payment_bypass_authorized",
            idempotency_key=f"pay-bypass-event:{event_key}" if key else event_key,
            actor_user_id=user.id,
            reason=reason.strip(),
            payload_json=json.dumps(
                {
                    "permission": P.PAYMENT_BYPASS,
                    "actor_user_id": user.id,
                    "bypass_id": row.id,
                    "gate_before": gate_before,
                    "gate_after": job.payment_status,
                    "idempotency_key": key,
                    "accurate_outstanding_unchanged": True,
                }
            ),
        )
    )
    await session.commit()
    await session.refresh(row)
    return row


async def revoke_payment_bypass(
    session: AsyncSession,
    user: User,
    bypass_id: int,
    *,
    reason: str,
) -> PaymentBypass:
    _require(user, P.PAYMENT_REVOKE)
    if not reason.strip():
        raise HTTPException(422, "Alasan pencabutan wajib")
    row = await session.get(PaymentBypass, bypass_id)
    if row is None or not row.active:
        raise HTTPException(404, "Bypass tidak aktif")
    job = await get_job(session, row.job_id)
    job = await _lock_payment_job(session, user, job)
    await session.refresh(row)
    if not row.active:
        raise HTTPException(409, "Bypass sudah dicabut")
    from app.services.production.payment_gate import (
        effective_status,
        job_has_production_progress,
    )

    gate_before = await effective_status(session, job.id)
    had_progress = await job_has_production_progress(session, job.id)
    row.active = False
    row.revoked_by = user.id
    row.revoke_reason = reason
    row.revoked_at = datetime.now(UTC)
    await session.flush()
    await _refresh_payment_gate(session, job)
    gate_after = job.payment_status
    exception = bool(
        had_progress and gate_before == "bypassed" and gate_after == "pending"
    )
    if exception:
        job.payment_review_required = True
    session.add(
        ProductionEvent(
            job_id=job.id,
            event_type="payment_bypass_revoked",
            idempotency_key=(
                f"pay-bypass-revoke:{row.id}:"
                f"{int(datetime.now(UTC).timestamp())}"
            ),
            actor_user_id=user.id,
            reason=reason.strip(),
            payload_json=json.dumps(
                {
                    "bypass_id": row.id,
                    "permission": P.PAYMENT_REVOKE,
                    "actor_user_id": user.id,
                    "gate_before": gate_before,
                    "gate_after": gate_after,
                    "financial_exception": exception,
                    "payment_review_required": bool(job.payment_review_required),
                }
            ),
        )
    )
    await session.commit()
    await session.refresh(row)
    return row


async def invalidate_receipt(
    session: AsyncSession,
    user: User,
    receipt_id: int,
    *,
    reason: str,
) -> PaymentReceiptRef:
    _require(user, P.PAYMENT_REVOKE)
    if not reason.strip():
        raise HTTPException(422, "Alasan pencabutan wajib")
    row = await session.get(PaymentReceiptRef, receipt_id)
    if row is None:
        raise HTTPException(404, "Receipt tidak ditemukan")
    job = await get_job(session, row.job_id)
    job = await _lock_payment_job(session, user, job)
    await session.refresh(row)
    if row.status != "valid":
        await _refresh_payment_gate(session, job)
        await session.commit()
        return row
    from app.services.production.payment_gate import (
        effective_status,
        job_has_production_progress,
    )

    gate_before = await effective_status(session, job.id)
    had_progress = await job_has_production_progress(session, job.id)
    row.status = "invalidated"
    row.note = (row.note or "") + f" | invalidated: {reason}"
    await session.flush()
    await _refresh_payment_gate(session, job)
    gate_after = job.payment_status
    # Financial exception: production already progressed and gate lost verified evidence.
    # Never delete or rewrite physical production history.
    exception = bool(
        had_progress
        and gate_before == "approved"
        and gate_after == "pending"
    )
    if exception:
        job.payment_review_required = True
    # Append-only audit event (never silent overwrite).
    session.add(
        ProductionEvent(
            job_id=job.id,
            event_type="payment_receipt_invalidated",
            idempotency_key=f"pay-invalidate:{row.id}:{int(datetime.now(UTC).timestamp())}",
            actor_user_id=user.id,
            reason=reason.strip(),
            payload_json=json.dumps(
                {
                    "receipt_id": row.id,
                    "accurate_receipt_id": row.accurate_receipt_id,
                    "gate_before": gate_before,
                    "gate_after": gate_after,
                    "financial_exception": exception,
                    "payment_review_required": bool(job.payment_review_required),
                    "physical_history_preserved": True,
                }
            ),
        )
    )
    if exception:
        session.add(
            ProductionEvent(
                job_id=job.id,
                event_type="payment_financial_exception",
                idempotency_key=(
                    f"pay-fin-exc:{row.id}:{int(datetime.now(UTC).timestamp())}"
                ),
                actor_user_id=user.id,
                reason=reason.strip(),
                payload_json=json.dumps(
                    {
                        "receipt_id": row.id,
                        "requires_authorized_review": True,
                        "note": (
                            "Verified payment lost after production progress; "
                            "physical output/SJ/POD history unchanged"
                        ),
                    }
                ),
            )
        )
    await session.commit()
    await session.refresh(row)
    return row


# ---- Schedule ----


async def _resolve_operator(
    session: AsyncSession, job: ProductionJob, operator_user_id: int | None
) -> User | None:
    """Official operator identity: active, same-branch, authorized for output input."""
    if operator_user_id is None:
        return None
    target = await session.get(User, operator_user_id)
    if target is None or not target.is_active:
        raise HTTPException(422, "Operator harus user aktif")
    from app.authorization.evaluator import Resource, evaluate
    from app.authorization.service import load_access

    scoped = False
    # Nested savepoint: load_access may fail (missing auth tables / shadow probe)
    # without poisoning the outer schedule transaction used by legacy fallback.
    try:
        async with session.begin_nested():
            access = await load_access(session, target.id, lock=False)
            scoped = evaluate(
                access, "output.record", Resource(job.branch_id, None)
            ).allowed
    except Exception:
        scoped = False
    legacy = (
        "production.output.confirm" in (target.permissions or [])
        and job.branch_id in (target.branch_ids or [])
    )
    if not (scoped or legacy):
        raise HTTPException(409, "Operator tidak berwenang input output pada cabang job ini")
    return target


async def _assert_machine_capacity(
    session: AsyncSession,
    job: ProductionJob,
    *,
    machine_name: str,
    work_date,
    add_qty: Decimal,
    so_line_id: str,
    color_pass: int = 1,
    exclude_assignment_id: int | None = None,
) -> None:
    """Machine/day capacity from the configured master. No master means no check.

    Passes of one line are the same physical cups, so per line the day load is
    the largest single pass, not the sum of passes.
    """
    from app.models.production.operations import ProductionMachine

    configured = await session.scalar(
        select(func.count())
        .select_from(ProductionMachine)
        .where(ProductionMachine.branch_id == job.branch_id, ProductionMachine.active.is_(True))
    )
    if not int(configured or 0):
        return
    machine = await session.scalar(
        select(ProductionMachine).where(
            ProductionMachine.branch_id == job.branch_id,
            ProductionMachine.name == machine_name,
            ProductionMachine.active.is_(True),
        )
    )
    if machine is None:
        raise HTTPException(409, "Mesin tidak terdaftar/aktif pada master mesin cabang")
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtext(f"machine:{job.branch_id}:{machine.id}:{work_date}")))
    )
    q = (
        select(
            ScheduleAssignment.job_id,
            ScheduleAssignment.so_line_id,
            ScheduleAssignment.color_pass,
            func.sum(ScheduleAssignment.qty_planned - ScheduleAssignment.qty_cancelled_remaining),
        )
        .where(
            ScheduleAssignment.branch_id == job.branch_id,
            ScheduleAssignment.machine_name == machine_name,
            ScheduleAssignment.work_date == work_date,
        )
        .group_by(ScheduleAssignment.job_id, ScheduleAssignment.so_line_id, ScheduleAssignment.color_pass)
    )
    if exclude_assignment_id is not None:
        q = q.where(ScheduleAssignment.id != exclude_assignment_id)
    passes: dict[tuple, dict[int, Decimal]] = {}
    for jid, line, pass_no, qty in (await session.execute(q)).all():
        passes.setdefault((jid, line), {})[int(pass_no or 1)] = Decimal(qty or 0)
    mine = passes.pop((job.id, so_line_id), {})
    others = sum((max(v.values()) for v in passes.values()), Decimal(0))
    mine[int(color_pass)] = mine.get(int(color_pass), Decimal(0)) + add_qty
    total = others + max(mine.values())
    day_cap = Decimal(machine.capacity_per_shift) * int(machine.shifts_per_day or 1)
    if total > day_cap:
        raise HTTPException(
            409,
            f"Kapasitas mesin {machine.name} terlampaui pada {work_date} ({total} > {day_cap})",
        )


REQUIRE_SYNCED_LINE_QTY = True

_UNCLASSIFIED_PACKING = (
    "Proses produksi line belum resmi (unknown). Packing ditolak sampai "
    "klasifikasi print atau non-print tersedia."
)
_UNCLASSIFIED_LOADING = (
    "Proses produksi line belum resmi (unknown). Loading ditolak sampai "
    "klasifikasi print atau non-print tersedia."
)
_MISSING_LINE_LOADING = (
    "Line SO belum memiliki JobLineQty. Loading ditolak sampai identitas line resmi tersedia."
)
_NON_PRINT_NOT_PRINT_CHAIN = (
    "Line non-print tidak masuk alur cetak. Packing langsung setelah payment dan bukti fisik."
)


def _classification_enforced() -> bool:
    """Production defaults reject unclassified physical moves. Legacy fixtures opt out."""
    return bool(REQUIRE_SYNCED_LINE_QTY or ENFORCE_LOADING_PACKING_CAP)


async def _require_payment_released(session: AsyncSession, job: ProductionJob) -> None:
    from app.services.production.payment_gate import effective_status

    if await effective_status(session, job.id) not in {"approved", "bypassed"}:
        raise HTTPException(409, "Payment belum disetujui/bypass")


async def _line_production_process(
    session: AsyncSession, job_id: int, so_line_id: str | None
) -> str | None:
    if not (so_line_id or "").strip():
        return None
    from app.models.production.prep import JobLineQty

    line = await session.scalar(
        select(JobLineQty).where(
            JobLineQty.job_id == job_id, JobLineQty.so_line_id == so_line_id
        )
    )
    if line is None:
        return None
    return (line.production_process or "").strip() or "unknown"


async def _reject_non_print_print_chain(
    session: AsyncSession, job_id: int, so_line_id: str | None
) -> None:
    if await _line_production_process(session, job_id, so_line_id) == "non_print":
        raise HTTPException(409, _NON_PRINT_NOT_PRINT_CHAIN)


async def _assert_schedule_cap(
    session: AsyncSession,
    job: ProductionJob,
    *,
    so_line_id: str,
    color_pass: int,
    add_qty: Decimal,
) -> None:
    """Per-line, per-pass planned qty may never exceed PO qty (caller holds job lock).

    Passes describe print layers over the same physical cups, so each pass is
    capped independently at the PO line qty; passes are never summed together.
    """
    from app.models.production.prep import JobLineQty

    line = await session.scalar(
        select(JobLineQty).where(
            JobLineQty.job_id == job.id, JobLineQty.so_line_id == so_line_id
        )
    )
    if line is None:
        if not REQUIRE_SYNCED_LINE_QTY:
            return
        raise HTTPException(409, "Qty PO untuk line ini belum tersinkron; jadwal ditolak")
    planned = await session.scalar(
        select(
            func.coalesce(
                func.sum(
                    ScheduleAssignment.qty_planned
                    - ScheduleAssignment.qty_cancelled_remaining
                ),
                0,
            )
        ).where(
            ScheduleAssignment.job_id == job.id,
            ScheduleAssignment.so_line_id == so_line_id,
            func.coalesce(ScheduleAssignment.color_pass, 1) == int(color_pass),
        )
    )
    planned = Decimal(planned or 0)
    cap = Decimal(line.po_qty or 0)
    if planned + add_qty > cap:
        raise HTTPException(
            409,
            f"Qty jadwal melebihi qty PO line ({planned + add_qty} > {cap}); sisa {max(cap - planned, Decimal(0))}",
        )


async def create_assignment(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    so_line_id: str,
    product_id: str | None,
    color_pass: int,
    operator_name: str,
    machine_name: str,
    work_date,
    qty_planned: Decimal,
    location_provenance: str | None = None,
    note: str | None = None,
    operator_user_id: int | None = None,
) -> ScheduleAssignment:
    _require(user, P.SCHEDULE_MANAGE)
    job = await _lock_payment_job(session, user, job)
    await _refresh_payment_gate(session, job)
    await _reject_non_print_print_chain(session, job.id, so_line_id)
    await gates_open_for_schedule(job, session)
    if qty_planned <= 0:
        raise HTTPException(422, "Qty rencana harus > 0")
    if int(color_pass) < 1:
        raise HTTPException(422, "color_pass tidak valid")
    await _assert_schedule_cap(
        session, job, so_line_id=so_line_id, color_pass=color_pass, add_qty=qty_planned
    )
    operator = await _resolve_operator(session, job, operator_user_id)
    if operator is not None:
        operator_name = operator.display_name
    await _assert_machine_capacity(
        session, job, machine_name=machine_name, work_date=work_date,
        add_qty=qty_planned, so_line_id=so_line_id, color_pass=color_pass,
    )
    seq = await session.scalar(
        select(func.coalesce(func.max(ScheduleAssignment.sequence_no), 0)).where(
            ScheduleAssignment.job_id == job.id,
            ScheduleAssignment.so_line_id == so_line_id,
            ScheduleAssignment.color_pass == color_pass,
        )
    )
    row = ScheduleAssignment(
        job_id=job.id,
        so_line_id=so_line_id,
        product_id=product_id,
        color_pass=color_pass,
        operator_name=operator_name,
        operator_user_id=operator.id if operator is not None else None,
        machine_name=machine_name,
        work_date=work_date,
        branch_id=job.branch_id,
        qty_planned=qty_planned,
        sequence_no=int(seq or 0) + 1,
        created_by=user.id,
        location_provenance=location_provenance,
        note=note,
    )
    session.add(row)
    await _mark_terproses(session, job)
    await session.commit()
    await session.refresh(row)
    return row


async def cancel_remaining(
    session: AsyncSession,
    user: User,
    assignment_id: int,
    *,
    reason: str,
) -> ScheduleAssignment:
    _require(user, P.SCHEDULE_MANAGE)
    row = await session.scalar(
        select(ScheduleAssignment)
        .where(ScheduleAssignment.id == assignment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404, "Assignment tidak ditemukan")
    job = await get_job(session, row.job_id)
    _branch(user, job.branch_id)
    remaining = row.qty_planned - row.qty_confirmed - row.qty_cancelled_remaining
    if remaining <= 0:
        raise HTTPException(409, "Tidak ada sisa qty yang dapat dibatalkan")
    # Never cancel confirmed output.
    row.qty_cancelled_remaining = row.qty_cancelled_remaining + remaining
    row.status = "cancelled_remaining"
    row.note = (row.note or "") + f" | cancel_remaining: {reason}"
    await session.commit()
    await session.refresh(row)
    return row


async def transfer_remaining(
    session: AsyncSession,
    user: User,
    assignment_id: int,
    *,
    operator_name: str,
    machine_name: str,
    work_date,
    reason: str,
    operator_user_id: int | None = None,
) -> ScheduleAssignment:
    _require(user, P.SCHEDULE_MANAGE)
    src = await session.scalar(
        select(ScheduleAssignment)
        .where(ScheduleAssignment.id == assignment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if src is None:
        raise HTTPException(404, "Assignment tidak ditemukan")
    job = await get_job(session, src.job_id)
    job = await _lock_payment_job(session, user, job)
    src = await session.scalar(
        select(ScheduleAssignment)
        .where(ScheduleAssignment.id == assignment_id)
        .execution_options(populate_existing=True)
    )
    remaining = src.qty_planned - src.qty_confirmed - src.qty_cancelled_remaining
    if remaining <= 0:
        raise HTTPException(409, "Tidak ada sisa untuk dipindahkan")
    operator = await _resolve_operator(session, job, operator_user_id)
    if operator is not None:
        operator_name = operator.display_name
    await _assert_machine_capacity(
        session, job, machine_name=machine_name, work_date=work_date,
        add_qty=remaining, so_line_id=src.so_line_id, color_pass=src.color_pass,
    )
    src.qty_cancelled_remaining = src.qty_cancelled_remaining + remaining
    src.status = "transferred"
    new_row = ScheduleAssignment(
        job_id=job.id,
        so_line_id=src.so_line_id,
        product_id=src.product_id,
        color_pass=src.color_pass,
        operator_name=operator_name,
        operator_user_id=operator.id if operator is not None else None,
        machine_name=machine_name,
        work_date=work_date,
        branch_id=job.branch_id,
        qty_planned=remaining,
        sequence_no=src.sequence_no + 1,
        created_by=user.id,
        location_provenance=f"transfer_from:{src.id}",
        note=f"transfer: {reason}",
    )
    session.add(new_row)
    await session.flush()
    src.transferred_to_id = new_row.id
    await session.commit()
    await session.refresh(new_row)
    return new_row


# ---- Sample + Output ----


async def upload_sample(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    file_name: str,
    storage_key: str,
    assignment_id: int | None = None,
) -> SampleVersion:
    _require(user, P.SAMPLE_UPLOAD)
    _branch(user, job.branch_id)
    sample_line_id: str | None = None
    if assignment_id is not None:
        sample_asg = await session.get(ScheduleAssignment, assignment_id)
        if sample_asg is not None and sample_asg.job_id == job.id:
            await _reject_non_print_print_chain(session, job.id, sample_asg.so_line_id)
            sample_line_id = str(sample_asg.so_line_id or "").strip() or None
    else:
        from app.models.production.prep import JobLineQty

        sample_lines = (
            await session.scalars(select(JobLineQty).where(JobLineQty.job_id == job.id))
        ).all()
        if sample_lines and all(
            (ln.production_process or "").strip() == "non_print" for ln in sample_lines
        ):
            raise HTTPException(409, _NON_PRINT_NOT_PRINT_CHAIN)
    from app.services.production.prep import require_print_preps_ready_for_sample

    await require_print_preps_ready_for_sample(
        session, job, so_line_id=sample_line_id
    )
    max_v = await session.scalar(
        select(func.coalesce(func.max(SampleVersion.version_no), 0)).where(
            SampleVersion.job_id == job.id
        )
    )
    ver = SampleVersion(
        job_id=job.id,
        assignment_id=assignment_id,
        version_no=int(max_v or 0) + 1,
        file_name=file_name,
        storage_key=storage_key,
        uploaded_by=user.id,
        status="pending",
        required_before_print=True,
    )
    session.add(ver)
    job.sample_status = "pending"
    await session.commit()
    await session.refresh(ver)
    return ver


async def decide_sample(
    session: AsyncSession,
    user: User,
    sample_id: int,
    *,
    decision: str,
    reason: str | None = None,
) -> SampleVersion:
    _require(user, P.SAMPLE_DECIDE)
    ver = await session.get(SampleVersion, sample_id)
    if ver is None:
        raise HTTPException(404, "Sample tidak ditemukan")
    job = await get_job(session, ver.job_id)
    _branch(user, job.branch_id)
    if decision not in {"approved", "rejected", "revised"}:
        raise HTTPException(422, "Keputusan sample tidak valid")
    if decision == "approved":
        from app.services.production.prep import require_print_preps_ready_for_sample

        sample_line_id = None
        if ver.assignment_id is not None:
            asg = await session.get(ScheduleAssignment, ver.assignment_id)
            if asg is not None and asg.job_id == job.id:
                sample_line_id = str(asg.so_line_id or "").strip() or None
        await require_print_preps_ready_for_sample(
            session, job, so_line_id=sample_line_id
        )
    ver.status = decision
    ver.decision_by = user.id
    ver.decision_reason = reason
    ver.decided_at = datetime.now(UTC)
    job.sample_status = decision if decision != "revised" else "pending"
    await session.commit()
    await session.refresh(ver)
    return ver


async def confirm_output(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    assignment_id: int,
    qty_physical: Decimal,
    qty_pass_ops: Decimal | None,
    color_pass: int,
    idempotency_key: str,
    lot_code: str | None = None,
    evidence_ref: str | None = None,
) -> ProductionEvent:
    from app.services.production.lifecycle import require_job_active

    require_job_active(job)
    _require(user, P.OUTPUT_CONFIRM)
    _branch(user, job.branch_id)
    assignment = await session.get(ScheduleAssignment, assignment_id)
    if assignment is None or assignment.job_id != job.id:
        raise HTTPException(404, "Assignment tidak valid")
    await _reject_non_print_print_chain(session, job.id, assignment.so_line_id)
    if assignment.status not in {"active", "completed"}:
        raise HTTPException(409, "Assignment tidak aktif")
    # Block print confirmation until required sample approved.
    if job.sample_status == "pending":
        raise HTTPException(409, "Sample wajib disetujui sebelum output cetak")
    if job.sample_status not in {"approved", "not_required"}:
        # rejected/revised without new approval
        if job.sample_status != "approved":
            req = await session.scalar(
                select(func.count())
                .select_from(SampleVersion)
                .where(
                    SampleVersion.job_id == job.id,
                    SampleVersion.required_before_print.is_(True),
                )
            )
            if int(req or 0) > 0 and job.sample_status != "approved":
                raise HTTPException(409, "Sample wajib disetujui sebelum output cetak")
    if qty_physical <= 0:
        raise HTTPException(422, "Qty fisik harus > 0")
    if not idempotency_key or not 8 <= len(idempotency_key.strip()) <= 120:
        raise HTTPException(422, "idempotency_key wajib 8-120 karakter")
    idempotency_key = idempotency_key.strip()
    qty_ops = qty_pass_ops if qty_pass_ops is not None else qty_physical
    job_id = job.id
    actor_id = user.id
    so_line_id = assignment.so_line_id

    def _same_output(row: ProductionEvent) -> bool:
        return (
            row.job_id == job_id
            and row.event_type == "output_confirmed"
            and row.assignment_id == assignment_id
            and row.qty_physical == qty_physical
            and row.qty_pass_ops == qty_ops
            and int(row.color_pass or 1) == int(color_pass)
            and (row.lot_code or None) == (lot_code or None)
            and (row.so_line_id or None) == (so_line_id or None)
        )

    # Idempotent replay before insert — same key+payload returns prior event.
    prior = await session.scalar(
        select(ProductionEvent).where(ProductionEvent.idempotency_key == idempotency_key)
    )
    if prior is not None:
        if not _same_output(prior):
            raise HTTPException(409, "Idempotency key payload tidak cocok")
        return prior

    remaining = (
        assignment.qty_planned
        - assignment.qty_confirmed
        - assignment.qty_cancelled_remaining
    )
    if qty_physical > remaining:
        raise HTTPException(409, "Qty melebihi sisa assignment")
    # Helper preparation ceiling (V49: output must not exceed prepared cups).
    from app.services.production.prep import helper_prepared_qty

    prepared = await helper_prepared_qty(session, job.id, assignment.so_line_id)
    if prepared > 0 or color_pass == 1:
        # If helper has recorded prep, enforce; color-pass 1 always requires prep>0
        # once any prep state exists for the line.
        from app.models.production.prep import PrepState

        has_helper = await session.scalar(
            select(func.count())
            .select_from(PrepState)
            .where(
                PrepState.job_id == job.id,
                PrepState.so_line_id == assignment.so_line_id,
                PrepState.role == "helper",
            )
        )
        if int(has_helper or 0) > 0:
            already = await session.scalar(
                select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
                    ProductionEvent.job_id == job.id,
                    ProductionEvent.so_line_id == assignment.so_line_id,
                    ProductionEvent.event_type.in_(
                        ["output_confirmed", "output_correction"]
                    ),
                    ProductionEvent.color_pass == 1,
                )
            )
            if color_pass == 1 and Decimal(already or 0) + qty_physical > prepared:
                raise HTTPException(409, "Output melebihi qty helper siap")
    event = ProductionEvent(
        job_id=job_id,
        assignment_id=assignment_id,
        event_type="output_confirmed",
        so_line_id=so_line_id,
        color_pass=color_pass,
        lot_code=lot_code,
        qty_physical=qty_physical,
        qty_pass_ops=qty_ops,
        idempotency_key=idempotency_key,
        actor_user_id=actor_id,
        evidence_ref=evidence_ref,
    )
    session.add(event)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        session.expunge_all()
        raced = await session.scalar(
            select(ProductionEvent).where(
                ProductionEvent.idempotency_key == idempotency_key
            )
        )
        if raced is None:
            raise HTTPException(
                409, "Idempotency key duplikat / concurrent submit"
            ) from exc
        if not _same_output(raced):
            raise HTTPException(409, "Idempotency key payload tidak cocok") from exc
        # Concurrent same-key same-payload: return canonical prior (no double qty).
        return raced
    assignment.qty_confirmed = assignment.qty_confirmed + qty_physical
    if (
        assignment.qty_confirmed + assignment.qty_cancelled_remaining
        >= assignment.qty_planned
    ):
        assignment.status = "completed"
    await _mark_terproses(session, job)
    await session.commit()
    await session.refresh(event)
    return event


async def record_reject(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    assignment_id: int,
    qty_physical: Decimal,
    color_pass: int,
    lot_code: str | None,
    reason: str,
    idempotency_key: str,
) -> ProductionEvent:
    from app.services.production.lifecycle import require_job_active

    require_job_active(job)
    _require(user, P.REJECT_RECORD)
    _branch(user, job.branch_id)
    if qty_physical <= 0 or not reason.strip():
        raise HTTPException(422, "Reject memerlukan qty dan alasan")
    assignment = await session.get(ScheduleAssignment, assignment_id)
    if assignment is None or assignment.job_id != job.id:
        raise HTTPException(404, "Assignment tidak valid")
    event = ProductionEvent(
        job_id=job.id,
        assignment_id=assignment_id,
        event_type="reject",
        so_line_id=assignment.so_line_id,
        color_pass=color_pass,
        lot_code=lot_code,
        qty_physical=qty_physical,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
        reason=reason.strip(),
    )
    session.add(event)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Idempotency key duplikat") from exc
    await session.refresh(event)
    return event


async def verify_reject(
    session: AsyncSession,
    user: User,
    event_id: int,
    *,
    approved_qty: Decimal,
    reason: str | None = None,
) -> ProductionEvent:
    """Authorized verification emits a compensating reject_verified event."""
    from app.services.production.lifecycle import require_job_active

    _require(user, P.REJECT_VERIFY)
    src = await session.get(ProductionEvent, event_id)
    if src is None or src.event_type != "reject":
        raise HTTPException(404, "Reject event tidak ditemukan")
    job = await get_job(session, src.job_id)
    require_job_active(job)
    _branch(user, job.branch_id)
    if approved_qty <= 0 or approved_qty > Decimal(src.qty_physical or 0):
        raise HTTPException(422, "Qty verifikasi reject tidak valid")
    event = ProductionEvent(
        job_id=job.id,
        assignment_id=src.assignment_id,
        event_type="reject_verified",
        so_line_id=src.so_line_id,
        color_pass=src.color_pass,
        lot_code=src.lot_code,
        qty_physical=approved_qty,
        idempotency_key=f"reject-verify:{src.id}:{approved_qty}",
        actor_user_id=user.id,
        reason=reason or f"verified_from:{src.id}",
        payload_json=f'{{"source_reject_id":{src.id}}}',
    )
    session.add(event)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Verifikasi reject sudah tercatat") from exc
    await session.refresh(event)
    return event


async def correct_output(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    source_event_id: int,
    qty_physical_delta: Decimal,
    reason: str,
    idempotency_key: str,
) -> ProductionEvent:
    """Compensating event — never silently overwrite confirmed output."""
    from app.services.production.lifecycle import require_job_active

    require_job_active(job)
    _require(user, P.OUTPUT_CONFIRM)
    _branch(user, job.branch_id)
    if not reason.strip():
        raise HTTPException(422, "Koreksi memerlukan alasan")
    if qty_physical_delta == 0:
        raise HTTPException(422, "Delta koreksi tidak boleh 0")
    src = await session.get(ProductionEvent, source_event_id)
    if src is None or src.job_id != job.id or src.event_type != "output_confirmed":
        raise HTTPException(404, "Output event sumber tidak ditemukan")
    # Snapshot primitives before commit/rollback — expired ORM attrs after
    # IntegrityError+rollback must not trigger sync lazy-load (MissingGreenlet).
    job_id = job.id
    reason_norm = reason.strip()
    payload_json = f'{{"source_output_id":{src.id}}}'
    source_assignment_id = src.assignment_id
    source_so_line_id = src.so_line_id
    source_color_pass = src.color_pass
    source_lot_code = src.lot_code
    actor_id = user.id

    def _same(row: ProductionEvent) -> bool:
        return (
            row.job_id == job_id
            and row.event_type == "output_correction"
            and row.qty_physical == qty_physical_delta
            and (row.reason or "") == reason_norm
            and row.payload_json == payload_json
        )

    prior = await session.scalar(
        select(ProductionEvent).where(ProductionEvent.idempotency_key == idempotency_key)
    )
    if prior is not None:
        if not _same(prior):
            raise HTTPException(409, "Idempotency key payload tidak cocok")
        return prior
    event = ProductionEvent(
        job_id=job_id,
        assignment_id=source_assignment_id,
        event_type="output_correction",
        so_line_id=source_so_line_id,
        color_pass=source_color_pass,
        lot_code=source_lot_code,
        qty_physical=qty_physical_delta,
        qty_pass_ops=qty_physical_delta,
        idempotency_key=idempotency_key,
        actor_user_id=actor_id,
        reason=reason_norm,
        payload_json=payload_json,
    )
    session.add(event)
    try:
        if source_assignment_id:
            assignment = await session.get(ScheduleAssignment, source_assignment_id)
            if assignment:
                assignment.qty_confirmed = assignment.qty_confirmed + qty_physical_delta
                if assignment.qty_confirmed < 0:
                    raise HTTPException(409, "Koreksi membuat qty confirmed negatif")
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        orig = getattr(exc, "orig", None)
        sqlstate = getattr(orig, "sqlstate", None)
        # asyncpg may wrap; also inspect str for unique violation text
        detail = str(orig or exc)
        if sqlstate != "23505" and "uq_production_events_idempotency" not in detail:
            raise
        # Clear expired identity-map state from the failed unit of work.
        session.expunge_all()
        raced = await session.scalar(
            select(ProductionEvent).where(ProductionEvent.idempotency_key == idempotency_key)
        )
        if raced is None:
            raise
        if not _same(raced):
            raise HTTPException(409, "Idempotency key payload tidak cocok") from exc
        return raced
    await session.refresh(event)
    return event


async def record_helper_output_verification(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    source_output_event_id: int,
    qty_physical: Decimal,
    idempotency_key: str,
    evidence_ref: str | None = None,
    reason: str | None = None,
) -> ProductionEvent:
    """Helper independently verifies operator output — append-only.

    Never rewrites operator history. Cumulative verified per source event cannot
    exceed operator net for that event. Packing eligibility uses this pool.
    """
    from app.services.production.lifecycle import require_job_active

    require_job_active(job)
    _require(user, P.OUTPUT_HELPER_VERIFY)
    _branch(user, job.branch_id)
    if qty_physical <= 0:
        raise HTTPException(422, "Qty verifikasi helper harus > 0")
    if not idempotency_key or not 8 <= len(idempotency_key.strip()) <= 120:
        raise HTTPException(422, "idempotency_key wajib 8-120 karakter")
    idempotency_key = idempotency_key.strip()
    src = await session.get(ProductionEvent, source_output_event_id)
    if src is None or src.job_id != job.id or src.event_type != "output_confirmed":
        raise HTTPException(404, "Output operator sumber tidak ditemukan")
    await _reject_non_print_print_chain(session, job.id, src.so_line_id)

    job_id = job.id
    src_id = src.id
    reason_norm = (reason or "").strip() or None
    evidence_norm = evidence_ref
    actor_id = user.id
    assignment_id = src.assignment_id
    so_line_id = src.so_line_id
    color_pass = src.color_pass or PHYSICAL_CUP_COLOR_PASS
    lot_code = src.lot_code
    operator_actor = src.actor_user_id

    def _same_helper(row: ProductionEvent) -> bool:
        if (
            row.job_id != job_id
            or row.event_type != HELPER_VERIFIED_EVENT
            or Decimal(row.qty_physical or 0) != qty_physical
            or (row.evidence_ref or None) != (evidence_norm or None)
            or (row.reason or None) != reason_norm
        ):
            return False
        try:
            data = json.loads(row.payload_json or "{}")
        except json.JSONDecodeError:
            return False
        return int(data.get("source_output_event_id") or 0) == src_id

    prior = await session.scalar(
        select(ProductionEvent).where(ProductionEvent.idempotency_key == idempotency_key)
    )
    if prior is not None:
        if not _same_helper(prior):
            raise HTTPException(409, "Idempotency key payload tidak cocok")
        return prior

    # Operator net for this source = confirmed + corrections tied to it.
    corrections = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job_id,
            ProductionEvent.event_type == "output_correction",
            ProductionEvent.payload_json.contains(f'"source_output_id":{src_id}'),
        )
    )
    operator_net = Decimal(src.qty_physical or 0) + Decimal(corrections or 0)
    if operator_net < 0:
        operator_net = Decimal("0")
    already = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job_id,
            ProductionEvent.event_type == HELPER_VERIFIED_EVENT,
            ProductionEvent.payload_json.contains(
                f'"source_output_event_id":{src_id}'
            ),
        )
    )
    remaining = operator_net - Decimal(already or 0)
    if remaining < 0:
        remaining = Decimal("0")
    if qty_physical > remaining:
        raise HTTPException(
            409,
            f"Verifikasi melebihi sisa output operator (remaining={remaining})",
        )
    # Lock source row to serialize concurrent verifies.
    await session.execute(
        select(ProductionEvent)
        .where(ProductionEvent.id == src_id)
        .with_for_update()
    )
    # Re-check after lock.
    already2 = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job_id,
            ProductionEvent.event_type == HELPER_VERIFIED_EVENT,
            ProductionEvent.payload_json.contains(
                f'"source_output_event_id":{src_id}'
            ),
        )
    )
    remaining2 = operator_net - Decimal(already2 or 0)
    if qty_physical > remaining2:
        raise HTTPException(
            409,
            f"Verifikasi melebihi sisa output operator (remaining={remaining2})",
        )
    payload = {
        "source_output_event_id": src_id,
        "assignment_id": assignment_id,
        "color_pass": int(color_pass or PHYSICAL_CUP_COLOR_PASS),
        "operator_actor_user_id": operator_actor,
        "helper_actor_user_id": actor_id,
        "reason": reason_norm,
    }
    event = ProductionEvent(
        job_id=job_id,
        assignment_id=assignment_id,
        event_type=HELPER_VERIFIED_EVENT,
        so_line_id=so_line_id,
        color_pass=color_pass,
        lot_code=lot_code,
        qty_physical=qty_physical,
        qty_pass_ops=qty_physical,
        idempotency_key=idempotency_key,
        actor_user_id=actor_id,
        evidence_ref=evidence_norm,
        reason=reason_norm,
        payload_json=json.dumps(payload, separators=(",", ":")),
    )
    session.add(event)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        session.expunge_all()
        raced = await session.scalar(
            select(ProductionEvent).where(
                ProductionEvent.idempotency_key == idempotency_key
            )
        )
        if raced is None:
            raise HTTPException(
                409, "Idempotency key duplikat / concurrent verify"
            ) from exc
        if not _same_helper(raced):
            raise HTTPException(409, "Idempotency key payload tidak cocok") from exc
        return raced
    await _mark_terproses(session, job)
    await session.commit()
    await session.refresh(event)
    return event


async def cancel_sj(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    accurate_sj_id: str,
    reason: str,
    idempotency_key: str,
) -> ProductionEvent:
    """Append-only SJ cancel history. Never treats cancel as physical reversal.

    Rejects when unreversed Loading (or POD) exists for the SJ. Capacity release
    requires a separate authorized durable reversal (out of scope here).
    """
    from app.services.production.lifecycle import require_job_active

    require_job_active(job)
    _require(user, P.DELIVERY_MANAGE)
    _branch(user, job.branch_id)
    sj_id = (accurate_sj_id or "").strip()
    if not sj_id or not reason.strip():
        raise HTTPException(422, "Pembatalan SJ memerlukan identitas dan alasan")

    # Serialize against Loading under the same per-job row lock.
    locked = await session.scalar(
        select(ProductionJob)
        .where(ProductionJob.id == job.id)
        .with_for_update()
    )
    if locked is None:
        raise HTTPException(404, "Production job tidak ditemukan")

    existing = await session.scalar(
        select(ProductionEvent).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.event_type != "sj_cancelled":
            raise HTTPException(409, "Idempotency key duplikat")
        if (existing.accurate_sj_id or "").strip() != sj_id:
            raise HTTPException(409, "Idempotency key payload tidak cocok")
        return existing

    loaded = await _net_confirmed_loading_sum(
        session, job.id, accurate_sj_id=sj_id
    )
    if loaded > 0:
        raise HTTPException(
            409,
            "SJ memiliki Loading terkonfirmasi (net) — batalkan Loading dulu, "
            "pembatalan SJ terpisah",
        )
    podded = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "pod",
            ProductionEvent.accurate_sj_id == sj_id,
        )
    )
    if Decimal(podded or 0) > 0:
        raise HTTPException(
            409,
            "SJ memiliki POD — pembatalan ditolak",
        )

    event = ProductionEvent(
        job_id=job.id,
        event_type="sj_cancelled",
        qty_physical=Decimal("0"),
        accurate_sj_id=sj_id,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
        reason=reason.strip(),
        payload_json=json.dumps(
            {
                "event_type": "sj_cancelled",
                "job_id": job.id,
                "branch_id": job.branch_id,
                "accurate_sj_id": sj_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    session.add(event)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raced = await session.scalar(
            select(ProductionEvent).where(
                ProductionEvent.job_id == job.id,
                ProductionEvent.idempotency_key == idempotency_key,
            )
        )
        if raced is not None and raced.event_type == "sj_cancelled":
            if (raced.accurate_sj_id or "").strip() != sj_id:
                raise HTTPException(409, "Idempotency key payload tidak cocok") from exc
            return raced
        raise HTTPException(409, "Idempotency key duplikat") from exc
    await session.refresh(event)
    return event


async def record_packing(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    so_line_id: str,
    lot_code: str | None,
    qty_physical: Decimal,
    idempotency_key: str,
    evidence_ref: str | None = None,
) -> ProductionEvent:
    from app.services.production.lifecycle import require_job_active

    require_job_active(job)
    _require(user, P.PACKING_RECORD)
    _branch(user, job.branch_id)
    if qty_physical <= 0:
        raise HTTPException(422, "Qty packing harus > 0")
    if not idempotency_key or not 8 <= len(idempotency_key.strip()) <= 120:
        raise HTTPException(422, "idempotency_key wajib 8-120 karakter")
    idempotency_key = idempotency_key.strip()
    from app.models.production.prep import JobLineQty

    job_id = job.id
    actor_id = user.id
    so_line = (so_line_id or "").strip()
    lot_norm = lot_code
    evidence_norm = (evidence_ref or "").strip() or None

    def _same_packing(row: ProductionEvent) -> bool:
        return (
            row.job_id == job_id
            and row.event_type in PACKING_EVENT_TYPES
            and (row.so_line_id or "") == so_line
            and Decimal(row.qty_physical or 0) == qty_physical
            and (row.lot_code or None) == (lot_norm or None)
            and (row.evidence_ref or None) == evidence_norm
        )

    prior = await session.scalar(
        select(ProductionEvent).where(ProductionEvent.idempotency_key == idempotency_key)
    )
    if prior is not None:
        if not _same_packing(prior):
            raise HTTPException(409, "Idempotency key payload tidak cocok")
        return prior

    locked = await session.scalar(
        select(ProductionJob).where(ProductionJob.id == job_id).with_for_update()
    )
    if locked is None:
        raise HTTPException(404, "Production job tidak ditemukan")
    line_row = await session.scalar(
        select(JobLineQty).where(
            JobLineQty.job_id == job_id, JobLineQty.so_line_id == so_line
        )
    )
    process = ((line_row.production_process or "") if line_row is not None else "").strip()
    # Never invent print for unclassified lines — fail closed regardless of
    # legacy fixture flags that disable REQUIRE_SYNCED_LINE_QTY.
    if process not in {"print", "non_print"}:
        raise HTTPException(409, _UNCLASSIFIED_PACKING)
    if process == "non_print":
        await _require_payment_released(session, job)
        if line_row is None or line_row.po_qty is None:
            raise HTTPException(422, "Line non-print belum tersinkron")
        if not evidence_norm:
            raise HTTPException(422, "Bukti konfirmasi gudang wajib")
        packed = Decimal(
            await session.scalar(
                select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
                    ProductionEvent.job_id == job_id,
                    ProductionEvent.event_type.in_(list(PACKING_EVENT_TYPES)),
                    ProductionEvent.so_line_id == so_line,
                )
            )
            or 0
        )
        if packed + qty_physical > Decimal(line_row.po_qty):
            raise HTTPException(
                409,
                f"Konfirmasi gudang melebihi sisa PO (po={line_row.po_qty}, sudah={packed})",
            )
        event = ProductionEvent(
            job_id=job_id,
            event_type=CANONICAL_PACKING_EVENT,
            so_line_id=so_line,
            lot_code=lot_norm,
            qty_physical=qty_physical,
            idempotency_key=idempotency_key,
            actor_user_id=actor_id,
            evidence_ref=evidence_norm,
            payload_json=json.dumps(
                {
                    "authority": "warehouse_confirmation",
                    "so_line_id": so_line,
                    "evidence_ref": evidence_norm,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        session.add(event)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            session.expunge_all()
            raced = await session.scalar(
                select(ProductionEvent).where(
                    ProductionEvent.idempotency_key == idempotency_key
                )
            )
            if raced is None or not _same_packing(raced):
                raise HTTPException(409, "Idempotency key payload tidak cocok") from exc
            return raced
        await session.refresh(event)
        return event
    # Required passes from schedule for this SO line (default pass 1 if none).
    asg_rows = (
        await session.scalars(
            select(ScheduleAssignment).where(
                ScheduleAssignment.job_id == job_id,
                ScheduleAssignment.so_line_id == so_line,
            )
        )
    ).all()
    required = required_color_passes_from_assignments(asg_rows, so_line_id=so_line)
    # Packing authority = helper-verified pool (min across required passes).
    # Operator output alone is never packable stock. Never sum multi-color passes.
    # Owner decision: Loading is capped by this packing-verified quantity per SO line.
    pass_nets: list[Decimal] = []
    for pass_no in sorted(required):
        verified = await session.scalar(
            select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
                ProductionEvent.job_id == job_id,
                ProductionEvent.event_type.in_(list(HELPER_VERIFIED_EVENT_TYPES)),
                ProductionEvent.so_line_id == so_line,
                func.coalesce(ProductionEvent.color_pass, PHYSICAL_CUP_COLOR_PASS)
                == pass_no,
            )
        )
        rejected = await session.scalar(
            select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
                ProductionEvent.job_id == job_id,
                ProductionEvent.event_type.in_(list(REJECT_EVENT_TYPES)),
                ProductionEvent.so_line_id == so_line,
                func.coalesce(ProductionEvent.color_pass, PHYSICAL_CUP_COLOR_PASS)
                == pass_no,
            )
        )
        pass_nets.append(Decimal(verified or 0) - Decimal(rejected or 0))
    eligible = min(pass_nets) if pass_nets else Decimal("0")
    packed = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job_id,
            ProductionEvent.event_type.in_(list(PACKING_EVENT_TYPES)),
            ProductionEvent.so_line_id == so_line,
        )
    )
    available = eligible - Decimal(packed or 0)
    if available < 0:
        available = Decimal("0")
    if qty_physical > available:
        raise HTTPException(
            409,
            "Overpacking: melebihi qty helper-verified semua warna "
            f"(eligible={available})",
        )
    event = ProductionEvent(
        job_id=job_id,
        event_type=CANONICAL_PACKING_EVENT,
        so_line_id=so_line,
        lot_code=lot_norm,
        qty_physical=qty_physical,
        idempotency_key=idempotency_key,
        actor_user_id=actor_id,
        evidence_ref=evidence_norm,
    )
    session.add(event)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        session.expunge_all()
        raced = await session.scalar(
            select(ProductionEvent).where(
                ProductionEvent.idempotency_key == idempotency_key
            )
        )
        if raced is None or not _same_packing(raced):
            raise HTTPException(409, "Idempotency key payload tidak cocok") from exc
        return raced
    await session.refresh(event)
    return event


async def _cancelled_sj_ids(session: AsyncSession, job_id: int) -> set[str]:
    rows = (
        await session.scalars(
            select(ProductionEvent.accurate_sj_id).where(
                ProductionEvent.job_id == job_id,
                ProductionEvent.event_type == "sj_cancelled",
                ProductionEvent.accurate_sj_id.is_not(None),
            )
        )
    ).all()
    return {str(r).strip() for r in rows if r and str(r).strip()}


LOADING_EVENT = "loading"
LOADING_CANCEL_EVENT = "loading_cancelled"
LOADING_CANCEL_CONFIRMATION = "confirmation_cancel"
LOADING_CANCEL_PHYSICAL_RETURN = "physical_return"
LOADING_RETURN_REQUESTED = "loading_return_requested"
LOADING_RETURN_REJECTED = "loading_return_rejected"


def _event_payload(ev: ProductionEvent) -> dict:
    raw = getattr(ev, "payload_json", None) or ""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _reverses_event_id(ev: ProductionEvent) -> int | None:
    raw = _event_payload(ev).get("reverses_event_id")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _event_matches_line_filters(
    ev: ProductionEvent,
    *,
    accurate_sj_id: str | None = None,
    accurate_sj_line_id: str | None = None,
    so_line_id: str | None = None,
) -> bool:
    sj = (ev.accurate_sj_id or "").strip()
    if accurate_sj_id is not None and sj != accurate_sj_id.strip():
        return False
    if accurate_sj_line_id is not None:
        if (ev.accurate_sj_line_id or "").strip() != accurate_sj_line_id.strip():
            return False
    if so_line_id is not None:
        if (ev.so_line_id or "").strip() != so_line_id.strip():
            return False
    return True


async def _sum_event_qty(
    session: AsyncSession,
    job_id: int,
    event_type: str,
    *,
    accurate_sj_id: str | None = None,
    accurate_sj_line_id: str | None = None,
    so_line_id: str | None = None,
    reverses_event_id: int | None = None,
) -> Decimal:
    rows = (
        await session.scalars(
            select(ProductionEvent).where(
                ProductionEvent.job_id == job_id,
                ProductionEvent.event_type == event_type,
            )
        )
    ).all()
    total = Decimal("0")
    for ev in rows:
        if not _event_matches_line_filters(
            ev,
            accurate_sj_id=accurate_sj_id,
            accurate_sj_line_id=accurate_sj_line_id,
            so_line_id=so_line_id,
        ):
            continue
        if reverses_event_id is not None:
            if _reverses_event_id(ev) != reverses_event_id:
                continue
        total += Decimal(ev.qty_physical or 0)
    return total


async def _net_confirmed_loading_sum(
    session: AsyncSession,
    job_id: int,
    *,
    accurate_sj_id: str | None = None,
    accurate_sj_line_id: str | None = None,
    so_line_id: str | None = None,
) -> Decimal:
    """Net confirmed Loading = Σloading − Σloading_cancelled (exact identities).

    Authority is Accurate SJ line qty, not Packing. Cancelled confirmation qty
    is not active Loading. SJ document cancel is a separate concern.
    """
    gross = await _sum_event_qty(
        session,
        job_id,
        LOADING_EVENT,
        accurate_sj_id=accurate_sj_id,
        accurate_sj_line_id=accurate_sj_line_id,
        so_line_id=so_line_id,
    )
    cancelled = await _sum_event_qty(
        session,
        job_id,
        LOADING_CANCEL_EVENT,
        accurate_sj_id=accurate_sj_id,
        accurate_sj_line_id=accurate_sj_line_id,
        so_line_id=so_line_id,
    )
    net = gross - cancelled
    return net if net > 0 else Decimal("0")


# Compatibility aliases for older call sites / tests.
async def _physical_loading_sum(
    session: AsyncSession,
    job_id: int,
    *,
    accurate_sj_id: str | None = None,
    accurate_sj_line_id: str | None = None,
    so_line_id: str | None = None,
) -> Decimal:
    return await _net_confirmed_loading_sum(
        session,
        job_id,
        accurate_sj_id=accurate_sj_id,
        accurate_sj_line_id=accurate_sj_line_id,
        so_line_id=so_line_id,
    )


async def _active_loading_sum(
    session: AsyncSession,
    job_id: int,
    *,
    cancelled: set[str] | None = None,
    accurate_sj_id: str | None = None,
    accurate_sj_line_id: str | None = None,
    so_line_id: str | None = None,
) -> Decimal:
    del cancelled
    return await _net_confirmed_loading_sum(
        session,
        job_id,
        accurate_sj_id=accurate_sj_id,
        accurate_sj_line_id=accurate_sj_line_id,
        so_line_id=so_line_id,
    )


_PCS_UOM_ALIASES = frozenset({"PCS", "PC", "PIECE", "PIECES", "CUP", "CUPS"})


def _normalize_uom(raw: object) -> str:
    return str(raw or "").strip().upper()


def _require_sj_physical_pcs_uom(line: dict) -> str:
    """Loading authority is verified SJ qty in physical PCS."""
    uom = _normalize_uom(line.get("uom"))
    if not uom:
        raise HTTPException(
            409,
            "UOM baris SJ tidak ada — Loading PCS diblokir",
        )
    if uom not in _PCS_UOM_ALIASES:
        raise HTTPException(
            409,
            f"UOM baris SJ harus PCS untuk Loading (uom={uom})",
        )
    return uom


def _require_whole_physical_pcs(qty_physical: Decimal) -> Decimal:
    """Confirmed Loading must be whole PCS — no silent truncate/round."""
    q = Decimal(qty_physical)
    if q <= 0:
        raise HTTPException(422, "Qty loading harus > 0")
    if q != q.to_integral_value():
        raise HTTPException(
            409,
            "Qty loading fisik PCS tidak boleh fraksional",
        )
    return q


def _authorized_base_qty(line: dict) -> Decimal:
    """Verified SJ line capacity in physical PCS: quantity × unitRatio."""
    if line.get("unit_ratio_verified") is False:
        raise HTTPException(409, "Qty/unit_ratio SJ line tidak valid")
    if line.get("qty_verified") is False:
        raise HTTPException(409, "Qty/unit_ratio SJ line tidak valid")
    qty = line.get("quantity")
    ratio = line.get("unit_ratio")
    if qty is None or ratio is None:
        raise HTTPException(409, "Qty/unit_ratio SJ line tidak valid")
    try:
        q = Decimal(str(qty))
        r = Decimal(str(ratio))
    except Exception as exc:
        raise HTTPException(409, "Qty/unit_ratio SJ line tidak valid") from exc
    if q < 0 or r <= 0:
        raise HTTPException(409, "Qty/unit_ratio SJ line tidak valid")
    return q * r


def _loading_identity_matches(
    existing: ProductionEvent,
    *,
    job: ProductionJob,
    accurate_sj_id: str,
    accurate_sj_number: str,
    accurate_sj_line_id: str,
    so_line_id: str,
    qty_physical: Decimal,
) -> bool:
    """Canonical Loading identity — field compare, not JSON key order."""
    if existing.event_type != LOADING_EVENT or existing.job_id != job.id:
        return False
    if (existing.accurate_sj_id or "").strip() != accurate_sj_id:
        return False
    if (existing.accurate_sj_number or "").strip() != accurate_sj_number:
        return False
    if (existing.accurate_sj_line_id or "").strip() != accurate_sj_line_id:
        return False
    if (existing.so_line_id or "").strip() != so_line_id:
        return False
    if Decimal(existing.qty_physical or 0) != Decimal(qty_physical):
        return False
    payload = _event_payload(existing)
    if "branch_id" in payload and str(payload.get("branch_id") or "") != str(
        job.branch_id
    ):
        return False
    return True


def _loading_cancel_identity_matches(
    existing: ProductionEvent,
    *,
    job: ProductionJob,
    source_event_id: int,
    qty_physical: Decimal,
    cancel_kind: str,
) -> bool:
    if existing.event_type != LOADING_CANCEL_EVENT or existing.job_id != job.id:
        return False
    if _reverses_event_id(existing) != source_event_id:
        return False
    if Decimal(existing.qty_physical or 0) != Decimal(qty_physical):
        return False
    payload = _event_payload(existing)
    if str(payload.get("cancel_kind") or "") != cancel_kind:
        return False
    if "branch_id" in payload and str(payload.get("branch_id") or "") != str(
        job.branch_id
    ):
        return False
    return True


ENFORCE_LOADING_PACKING_CAP = True


async def _confirmed_packing_qty(
    session: AsyncSession, job_id: int, so_line_id: str
) -> tuple[int, Decimal]:
    evidence = int(
        await session.scalar(
            select(func.count())
            .select_from(ProductionEvent)
            .where(
                ProductionEvent.job_id == job_id,
                ProductionEvent.event_type.in_(list(PACKING_EVENT_TYPES)),
                ProductionEvent.so_line_id == so_line_id,
            )
        )
        or 0
    )
    packed = Decimal(
        await session.scalar(
            select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
                ProductionEvent.job_id == job_id,
                ProductionEvent.event_type.in_(list(PACKING_EVENT_TYPES)),
                ProductionEvent.so_line_id == so_line_id,
            )
        )
        or 0
    )
    return evidence, packed


async def _physical_readiness_qty(
    session: AsyncSession, job_id: int, so_line_id: str
) -> tuple[Decimal | None, Decimal | None, str]:
    """Qty that may be loaded, the PO line qty, and a gap code.

    Print and non-print share one physical authority: confirmed packing.
    Confirmed print output is gesut progress and does not make goods READY.
    Unknown process and a missing JobLineQty fail closed when classification
    is enforced. None is missing evidence, never a verified zero.
    """
    from app.models.production.prep import JobLineQty

    line = await session.scalar(
        select(JobLineQty).where(
            JobLineQty.job_id == job_id, JobLineQty.so_line_id == so_line_id
        )
    )
    if line is None:
        if _classification_enforced():
            return None, None, "missing_line"
        _count, packed = await _confirmed_packing_qty(session, job_id, so_line_id)
        return packed, None, ""
    po_qty = Decimal(line.po_qty) if line.po_qty is not None else None
    process = (line.production_process or "").strip()
    # Unknown process always fail-closed for Loading readiness (never invent print).
    if process not in {"print", "non_print"}:
        return None, po_qty, "unknown_process"
    evidence, packed = await _confirmed_packing_qty(session, job_id, so_line_id)
    if evidence <= 0:
        return None, po_qty, "no_evidence"
    return packed, po_qty, ""


async def record_loading(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    accurate_sj_id: str,
    accurate_sj_number: str,
    accurate_sj_line_id: str,
    so_line_id: str,
    qty_physical: Decimal,
    idempotency_key: str,
    evidence_ref: str | None = None,
) -> ProductionEvent:
    """Confirm Loading within SJ line capacity and valid packed qty."""
    from app.services.production.lifecycle import require_job_active

    require_job_active(job)
    _require(user, P.DELIVERY_MANAGE)
    _branch(user, job.branch_id)
    sj_id = (accurate_sj_id or "").strip()
    sj_no = (accurate_sj_number or "").strip()
    sj_line = (accurate_sj_line_id or "").strip()
    so_line = (so_line_id or "").strip()
    if not sj_id or not sj_no:
        raise HTTPException(422, "Identitas SJ Accurate wajib")
    if not sj_line or not so_line:
        raise HTTPException(422, "Identitas baris SJ dan SO line wajib")
    qty_physical = _require_whole_physical_pcs(qty_physical)

    existing = await session.scalar(
        select(ProductionEvent).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if not _loading_identity_matches(
            existing,
            job=job,
            accurate_sj_id=sj_id,
            accurate_sj_number=sj_no,
            accurate_sj_line_id=sj_line,
            so_line_id=so_line,
            qty_physical=qty_physical,
        ):
            raise HTTPException(409, "Idempotency key payload tidak cocok")
        return existing

    from app.services.accurate_evidence import (
        require_valid_sj,
        resolve_sj_loading_line,
    )

    evidence = await require_valid_sj(
        accurate_sj_id=sj_id,
        accurate_sj_number=sj_no,
        expected_so_number=job.accurate_so_number,
        expected_branch_id=job.branch_id,
    )
    line = resolve_sj_loading_line(
        evidence, accurate_sj_line_id=sj_line, so_line_id=so_line
    )
    uom = _require_sj_physical_pcs_uom(line)
    authorized_base = _authorized_base_qty(line)

    locked = await session.scalar(
        select(ProductionJob)
        .where(ProductionJob.id == job.id)
        .with_for_update()
    )
    if locked is None:
        raise HTTPException(404, "Production job tidak ditemukan")

    cancelled = await _cancelled_sj_ids(session, job.id)
    if sj_id in cancelled:
        raise HTTPException(409, "SJ sudah dibatalkan; gunakan SJ aktif")

    legacy = await session.scalar(
        select(func.count())
        .select_from(ProductionEvent)
        .where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == LOADING_EVENT,
            ProductionEvent.accurate_sj_id == sj_id,
            or_(
                ProductionEvent.accurate_sj_line_id.is_(None),
                ProductionEvent.so_line_id.is_(None),
            ),
        )
    )
    if int(legacy or 0) > 0:
        raise HTTPException(
            409,
            "SJ memiliki Loading legacy tanpa identitas baris — rekonsiliasi wajib",
        )

    # Owner authority: SJ line verified PCS − net confirmed Loading for that line.
    # Owner decision: Loading <= SJ-line remaining and <= packing-verified qty minus prior Loading.
    net_loaded = await _net_confirmed_loading_sum(
        session,
        job.id,
        accurate_sj_id=sj_id,
        accurate_sj_line_id=sj_line,
        so_line_id=so_line,
    )
    remaining_sj = authorized_base - net_loaded
    if qty_physical > remaining_sj:
        raise HTTPException(
            409,
            f"Loading melebihi sisa otorisasi baris SJ (sisa={remaining_sj})",
        )

    readiness, po_qty, readiness_gap = await _physical_readiness_qty(session, job.id, so_line)
    if readiness_gap == "unknown_process":
        raise HTTPException(409, _UNCLASSIFIED_LOADING)
    if readiness_gap == "missing_line":
        raise HTTPException(409, _MISSING_LINE_LOADING)
    if await _line_production_process(session, job.id, so_line) == "non_print":
        await _require_payment_released(session, job)
    if ENFORCE_LOADING_PACKING_CAP:
        loaded_line = await _net_confirmed_loading_sum(
            session, job.id, so_line_id=so_line
        )
        if readiness is None or loaded_line + qty_physical > readiness:
            raise HTTPException(
                409,
                "Loading melebihi qty packing sah "
                f"(kesiapan={readiness if readiness is not None else 'UNVERIFIED'}, "
                f"sudah loading={loaded_line})",
            )
        if po_qty is not None and loaded_line + qty_physical > po_qty:
            raise HTTPException(
                409,
                f"Loading melebihi sisa pemenuhan PO (po={po_qty}, sudah loading={loaded_line})",
            )

    payload = {
        "event_type": LOADING_EVENT,
        "job_id": job.id,
        "branch_id": job.branch_id,
        "accurate_sj_id": sj_id,
        "accurate_sj_number": sj_no,
        "accurate_sj_line_id": sj_line,
        "so_line_id": so_line,
        "qty_physical": str(qty_physical),
        "uom": uom,
        "accurate_so_id": line.get("accurate_so_id"),
        "accurate_item_id": line.get("accurate_item_id"),
        "quantity": str(line.get("quantity")),
        "unit_ratio": str(line.get("unit_ratio")),
        "authorized_base": str(authorized_base),
        "so_line_id_source": line.get("so_line_id_source"),
        "authority": "accurate_sj_line",
    }
    event = ProductionEvent(
        job_id=job.id,
        event_type=LOADING_EVENT,
        so_line_id=so_line,
        qty_physical=qty_physical,
        accurate_sj_id=sj_id,
        accurate_sj_number=sj_no,
        accurate_sj_line_id=sj_line,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
        evidence_ref=evidence_ref,
        payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
    )
    session.add(event)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raced = await session.scalar(
            select(ProductionEvent).where(
                ProductionEvent.job_id == job.id,
                ProductionEvent.idempotency_key == idempotency_key,
            )
        )
        if raced is not None and _loading_identity_matches(
            raced,
            job=job,
            accurate_sj_id=sj_id,
            accurate_sj_number=sj_no,
            accurate_sj_line_id=sj_line,
            so_line_id=so_line,
            qty_physical=qty_physical,
        ):
            return raced
        raise HTTPException(409, "Idempotency key payload tidak cocok") from exc
    await session.refresh(event)
    return event


def _request_event_id_from_payload(ev: ProductionEvent) -> int | None:
    raw = _event_payload(ev).get("request_event_id")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


async def _loading_return_request_terminal(
    session: AsyncSession, job_id: int, request_id: int
) -> str | None:
    """Return 'approved' | 'rejected' | None if still open."""
    rows = (
        await session.scalars(
            select(ProductionEvent).where(
                ProductionEvent.job_id == job_id,
                ProductionEvent.event_type.in_(
                    [LOADING_RETURN_REJECTED, LOADING_CANCEL_EVENT]
                ),
            )
        )
    ).all()
    for ev in rows:
        if _request_event_id_from_payload(ev) != request_id:
            continue
        if ev.event_type == LOADING_RETURN_REJECTED:
            return "rejected"
        if (
            ev.event_type == LOADING_CANCEL_EVENT
            and _event_payload(ev).get("cancel_kind") == LOADING_CANCEL_PHYSICAL_RETURN
        ):
            return "approved"
    return None


async def _open_return_request_qty(
    session: AsyncSession,
    job_id: int,
    source_event_id: int,
    *,
    exclude_request_id: int | None = None,
) -> Decimal:
    """Sum qty on open (not approved/rejected) return requests for a Loading."""
    rows = (
        await session.scalars(
            select(ProductionEvent).where(
                ProductionEvent.job_id == job_id,
                ProductionEvent.event_type == LOADING_RETURN_REQUESTED,
            )
        )
    ).all()
    total = Decimal("0")
    for ev in rows:
        if exclude_request_id is not None and ev.id == exclude_request_id:
            continue
        if _reverses_event_id(ev) != source_event_id:
            continue
        terminal = await _loading_return_request_terminal(session, job_id, ev.id)
        if terminal is None:
            total += Decimal(ev.qty_physical or 0)
    return total


async def _cancellable_loading_remaining(
    session: AsyncSession,
    job: ProductionJob,
    source: ProductionEvent,
    *,
    qty_physical: Decimal,
    reserve_open_requests: bool,
) -> tuple[str, str, str, Decimal, Decimal]:
    """Shared guards for confirmation cancel and physical return approve/request."""
    sj_id = (source.accurate_sj_id or "").strip()
    sj_line = (source.accurate_sj_line_id or "").strip()
    so_line = (source.so_line_id or "").strip()
    if not sj_id or not sj_line or not so_line:
        raise HTTPException(
            409,
            "Loading legacy tanpa identitas baris tidak dapat dibatalkan lewat jalur ini",
        )
    already_cancelled = await _sum_event_qty(
        session,
        job.id,
        LOADING_CANCEL_EVENT,
        reverses_event_id=source.id,
    )
    remaining_on_event = Decimal(source.qty_physical or 0) - already_cancelled
    if reserve_open_requests:
        remaining_on_event -= await _open_return_request_qty(
            session, job.id, source.id
        )
    if remaining_on_event <= 0:
        raise HTTPException(409, "Loading sumber sudah dibatalkan penuh")
    if qty_physical > remaining_on_event:
        raise HTTPException(
            409,
            f"Qty batal melebihi sisa Loading event (sisa={remaining_on_event})",
        )
    net_sj = await _net_confirmed_loading_sum(
        session, job.id, accurate_sj_id=sj_id
    )
    podded = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "pod",
            ProductionEvent.accurate_sj_id == sj_id,
        )
    )
    pod_qty = Decimal(podded or 0)
    # Open return requests do not release net; POD guard uses net after this cancel.
    if net_sj - qty_physical < pod_qty:
        raise HTTPException(
            409,
            "Tidak boleh membatalkan qty yang sudah ter-cover POD",
        )
    return sj_id, sj_line, so_line, remaining_on_event, pod_qty


async def cancel_loading(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    source_event_id: int,
    qty_physical: Decimal,
    reason: str,
    idempotency_key: str,
    cancel_kind: str = LOADING_CANCEL_CONFIRMATION,
    evidence_attachment_id: int | None = None,
    evidence_ref: str | None = None,
) -> ProductionEvent:
    """confirmation_cancel only — physical_return uses request/approve APIs."""
    from app.services.production.lifecycle import require_job_active

    require_job_active(job)
    _require(user, P.DELIVERY_MANAGE)
    _branch(user, job.branch_id)
    kind = (cancel_kind or "").strip() or LOADING_CANCEL_CONFIRMATION
    if kind == LOADING_CANCEL_PHYSICAL_RETURN:
        raise HTTPException(
            422,
            "physical_return memakai API return-request/approve — "
            "bukan cancel langsung",
        )
    if kind != LOADING_CANCEL_CONFIRMATION:
        raise HTTPException(422, "Jenis pembatalan Loading tidak valid")
    if not (reason or "").strip():
        raise HTTPException(422, "Alasan pembatalan Loading wajib")
    if evidence_attachment_id is not None:
        raise HTTPException(
            422,
            "confirmation_cancel tidak memakai evidence_attachment_id",
        )
    del evidence_ref  # optional note unused for confirmation path
    qty_physical = _require_whole_physical_pcs(qty_physical)

    existing = await session.scalar(
        select(ProductionEvent).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if not _loading_cancel_identity_matches(
            existing,
            job=job,
            source_event_id=source_event_id,
            qty_physical=qty_physical,
            cancel_kind=kind,
        ):
            raise HTTPException(409, "Idempotency key payload tidak cocok")
        return existing

    locked = await session.scalar(
        select(ProductionJob)
        .where(ProductionJob.id == job.id)
        .with_for_update()
    )
    if locked is None:
        raise HTTPException(404, "Production job tidak ditemukan")

    source = await session.get(ProductionEvent, source_event_id)
    if (
        source is None
        or source.job_id != job.id
        or source.event_type != LOADING_EVENT
    ):
        raise HTTPException(404, "Event Loading sumber tidak ditemukan")

    sj_id, sj_line, so_line, _, _ = await _cancellable_loading_remaining(
        session,
        job,
        source,
        qty_physical=qty_physical,
        reserve_open_requests=True,
    )

    payload = {
        "event_type": LOADING_CANCEL_EVENT,
        "job_id": job.id,
        "branch_id": job.branch_id,
        "actor_user_id": user.id,
        "reverses_event_id": int(source.id),
        "cancel_kind": kind,
        "accurate_sj_id": sj_id,
        "accurate_sj_number": (source.accurate_sj_number or "").strip(),
        "accurate_sj_line_id": sj_line,
        "so_line_id": so_line,
        "qty_physical": str(qty_physical),
        "claims_physical_return": False,
        "evidence_attachment_id": None,
        "approval_policy": "confirmation_cancel_no_dual_approval",
    }
    event = ProductionEvent(
        job_id=job.id,
        event_type=LOADING_CANCEL_EVENT,
        so_line_id=so_line,
        qty_physical=qty_physical,
        accurate_sj_id=sj_id,
        accurate_sj_number=source.accurate_sj_number,
        accurate_sj_line_id=sj_line,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
        reason=reason.strip(),
        evidence_ref=None,
        payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
    )
    session.add(event)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raced = await session.scalar(
            select(ProductionEvent).where(
                ProductionEvent.job_id == job.id,
                ProductionEvent.idempotency_key == idempotency_key,
            )
        )
        if raced is not None and _loading_cancel_identity_matches(
            raced,
            job=job,
            source_event_id=source_event_id,
            qty_physical=qty_physical,
            cancel_kind=kind,
        ):
            return raced
        raise HTTPException(409, "Idempotency key payload tidak cocok") from exc
    await session.refresh(event)
    return event


def _return_request_identity_matches(
    existing: ProductionEvent,
    *,
    job: ProductionJob,
    source_event_id: int,
    qty_physical: Decimal,
    evidence_attachment_id: int,
) -> bool:
    if existing.event_type != LOADING_RETURN_REQUESTED or existing.job_id != job.id:
        return False
    if _reverses_event_id(existing) != source_event_id:
        return False
    if Decimal(existing.qty_physical or 0) != Decimal(qty_physical):
        return False
    payload = _event_payload(existing)
    if int(payload.get("evidence_attachment_id") or 0) != int(evidence_attachment_id):
        return False
    if "branch_id" in payload and str(payload.get("branch_id") or "") != str(
        job.branch_id
    ):
        return False
    return True


async def request_loading_return(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    source_event_id: int,
    qty_physical: Decimal,
    reason: str,
    idempotency_key: str,
    evidence_attachment_id: int,
) -> ProductionEvent:
    """Create physical-return request. Does NOT release Loading capacity."""
    _require(user, P.DELIVERY_LOADING_RETURN_REQUEST)
    _branch(user, job.branch_id)
    if not (reason or "").strip():
        raise HTTPException(422, "Alasan physical return wajib")
    qty_physical = _require_whole_physical_pcs(qty_physical)

    existing = await session.scalar(
        select(ProductionEvent).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if not _return_request_identity_matches(
            existing,
            job=job,
            source_event_id=source_event_id,
            qty_physical=qty_physical,
            evidence_attachment_id=evidence_attachment_id,
        ):
            raise HTTPException(409, "Idempotency key payload tidak cocok")
        return existing

    locked = await session.scalar(
        select(ProductionJob)
        .where(ProductionJob.id == job.id)
        .with_for_update()
    )
    if locked is None:
        raise HTTPException(404, "Production job tidak ditemukan")

    source = await session.get(ProductionEvent, source_event_id)
    if (
        source is None
        or source.job_id != job.id
        or source.event_type != LOADING_EVENT
    ):
        raise HTTPException(404, "Event Loading sumber tidak ditemukan")

    # Pending requests do not release capacity and do not hard-reserve it.
    # Over-subscription is fail-closed at approve under the job lock.
    sj_id, sj_line, so_line, _, _ = await _cancellable_loading_remaining(
        session,
        job,
        source,
        qty_physical=qty_physical,
        reserve_open_requests=False,
    )

    from app.services.production import attachments as attach_svc

    attachment = await attach_svc.validate_unbound_loading_return_attachment(
        session,
        job=job,
        accurate_sj_id=sj_id,
        attachment_id=int(evidence_attachment_id),
    )

    payload = {
        "event_type": LOADING_RETURN_REQUESTED,
        "job_id": job.id,
        "branch_id": job.branch_id,
        "actor_user_id": user.id,
        "requester_user_id": user.id,
        "reverses_event_id": int(source.id),
        "accurate_sj_id": sj_id,
        "accurate_sj_number": (source.accurate_sj_number or "").strip(),
        "accurate_sj_line_id": sj_line,
        "so_line_id": so_line,
        "qty_physical": str(qty_physical),
        "evidence_attachment_id": int(attachment.id),
        "releases_capacity": False,
        "approval_policy": "dual_control_loading_return",
    }
    event = ProductionEvent(
        job_id=job.id,
        event_type=LOADING_RETURN_REQUESTED,
        so_line_id=so_line,
        qty_physical=qty_physical,
        accurate_sj_id=sj_id,
        accurate_sj_number=source.accurate_sj_number,
        accurate_sj_line_id=sj_line,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
        reason=reason.strip(),
        evidence_ref=f"attachment:{attachment.id}",
        payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
    )
    session.add(event)
    try:
        await session.flush()
        await attach_svc.bind_attachments_to_event(
            session, {"loading_return_photo": attachment}, event.id
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raced = await session.scalar(
            select(ProductionEvent).where(
                ProductionEvent.job_id == job.id,
                ProductionEvent.idempotency_key == idempotency_key,
            )
        )
        if raced is not None and _return_request_identity_matches(
            raced,
            job=job,
            source_event_id=source_event_id,
            qty_physical=qty_physical,
            evidence_attachment_id=evidence_attachment_id,
        ):
            return raced
        raise HTTPException(409, "Idempotency key payload tidak cocok") from exc
    await session.refresh(event)
    return event


async def approve_loading_return(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    request_event_id: int,
    idempotency_key: str,
    reason: str | None = None,
) -> ProductionEvent:
    """Approve physical return → append loading_cancelled; releases capacity."""
    _require(user, P.DELIVERY_LOADING_RETURN_APPROVE)
    _branch(user, job.branch_id)

    existing = await session.scalar(
        select(ProductionEvent).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.event_type != LOADING_CANCEL_EVENT:
            raise HTTPException(409, "Idempotency key duplikat")
        payload = _event_payload(existing)
        if _request_event_id_from_payload(existing) != request_event_id:
            raise HTTPException(409, "Idempotency key payload tidak cocok")
        if payload.get("cancel_kind") != LOADING_CANCEL_PHYSICAL_RETURN:
            raise HTTPException(409, "Idempotency key payload tidak cocok")
        return existing

    locked = await session.scalar(
        select(ProductionJob)
        .where(ProductionJob.id == job.id)
        .with_for_update()
    )
    if locked is None:
        raise HTTPException(404, "Production job tidak ditemukan")

    req = await session.get(ProductionEvent, request_event_id)
    if (
        req is None
        or req.job_id != job.id
        or req.event_type != LOADING_RETURN_REQUESTED
    ):
        raise HTTPException(404, "Permintaan physical return tidak ditemukan")

    terminal = await _loading_return_request_terminal(session, job.id, req.id)
    if terminal == "approved":
        # Find prior approval for true idempotent replay without key
        raise HTTPException(409, "Permintaan physical return sudah disetujui")
    if terminal == "rejected":
        raise HTTPException(409, "Permintaan physical return sudah ditolak")

    if int(req.actor_user_id) == int(user.id):
        raise HTTPException(
            409,
            "Verifier harus berbeda dari requester physical return",
        )

    source_id = _reverses_event_id(req)
    if source_id is None:
        raise HTTPException(409, "Permintaan return tanpa sumber Loading")
    source = await session.get(ProductionEvent, source_id)
    if (
        source is None
        or source.job_id != job.id
        or source.event_type != LOADING_EVENT
    ):
        raise HTTPException(409, "Event Loading sumber tidak valid")

    qty_physical = _require_whole_physical_pcs(Decimal(req.qty_physical or 0))
    # Capacity uses committed cancels only — open requests do not reserve stock.
    # Concurrent approves serialize on job FOR UPDATE; loser sees reduced remaining.
    sj_id, sj_line, so_line, _, _ = await _cancellable_loading_remaining(
        session,
        job,
        source,
        qty_physical=qty_physical,
        reserve_open_requests=False,
    )

    req_payload = _event_payload(req)
    payload = {
        "event_type": LOADING_CANCEL_EVENT,
        "job_id": job.id,
        "branch_id": job.branch_id,
        "actor_user_id": user.id,
        "approver_user_id": user.id,
        "requester_user_id": int(req.actor_user_id),
        "request_event_id": int(req.id),
        "reverses_event_id": int(source.id),
        "cancel_kind": LOADING_CANCEL_PHYSICAL_RETURN,
        "accurate_sj_id": sj_id,
        "accurate_sj_number": (source.accurate_sj_number or "").strip(),
        "accurate_sj_line_id": sj_line,
        "so_line_id": so_line,
        "qty_physical": str(qty_physical),
        "claims_physical_return": True,
        "evidence_attachment_id": req_payload.get("evidence_attachment_id"),
        "approval_policy": "dual_control_loading_return",
        "releases_capacity": True,
    }
    event = ProductionEvent(
        job_id=job.id,
        event_type=LOADING_CANCEL_EVENT,
        so_line_id=so_line,
        qty_physical=qty_physical,
        accurate_sj_id=sj_id,
        accurate_sj_number=source.accurate_sj_number,
        accurate_sj_line_id=sj_line,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
        reason=(reason or req.reason or "physical_return_approved").strip(),
        evidence_ref=req.evidence_ref,
        payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
    )
    session.add(event)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raced = await session.scalar(
            select(ProductionEvent).where(
                ProductionEvent.job_id == job.id,
                ProductionEvent.idempotency_key == idempotency_key,
            )
        )
        if (
            raced is not None
            and raced.event_type == LOADING_CANCEL_EVENT
            and _request_event_id_from_payload(raced) == request_event_id
        ):
            return raced
        raise HTTPException(409, "Idempotency key payload tidak cocok") from exc
    await session.refresh(event)
    return event


async def reject_loading_return(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    request_event_id: int,
    reason: str,
    idempotency_key: str,
) -> ProductionEvent:
    """Reject physical-return request — no capacity change."""
    _require(user, P.DELIVERY_LOADING_RETURN_APPROVE)
    _branch(user, job.branch_id)
    if not (reason or "").strip():
        raise HTTPException(422, "Alasan penolakan physical return wajib")

    existing = await session.scalar(
        select(ProductionEvent).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.event_type != LOADING_RETURN_REJECTED:
            raise HTTPException(409, "Idempotency key duplikat")
        if _request_event_id_from_payload(existing) != request_event_id:
            raise HTTPException(409, "Idempotency key payload tidak cocok")
        return existing

    locked = await session.scalar(
        select(ProductionJob)
        .where(ProductionJob.id == job.id)
        .with_for_update()
    )
    if locked is None:
        raise HTTPException(404, "Production job tidak ditemukan")

    req = await session.get(ProductionEvent, request_event_id)
    if (
        req is None
        or req.job_id != job.id
        or req.event_type != LOADING_RETURN_REQUESTED
    ):
        raise HTTPException(404, "Permintaan physical return tidak ditemukan")

    terminal = await _loading_return_request_terminal(session, job.id, req.id)
    if terminal is not None:
        raise HTTPException(
            409,
            f"Permintaan physical return sudah {terminal}",
        )
    if int(req.actor_user_id) == int(user.id):
        raise HTTPException(
            409,
            "Verifier harus berbeda dari requester physical return",
        )

    payload = {
        "event_type": LOADING_RETURN_REJECTED,
        "job_id": job.id,
        "branch_id": job.branch_id,
        "actor_user_id": user.id,
        "approver_user_id": user.id,
        "requester_user_id": int(req.actor_user_id),
        "request_event_id": int(req.id),
        "reverses_event_id": _reverses_event_id(req),
        "qty_physical": str(req.qty_physical or 0),
        "releases_capacity": False,
        "approval_policy": "dual_control_loading_return",
    }
    event = ProductionEvent(
        job_id=job.id,
        event_type=LOADING_RETURN_REJECTED,
        so_line_id=req.so_line_id,
        qty_physical=Decimal(req.qty_physical or 0),
        accurate_sj_id=req.accurate_sj_id,
        accurate_sj_number=req.accurate_sj_number,
        accurate_sj_line_id=req.accurate_sj_line_id,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
        reason=reason.strip(),
        evidence_ref=req.evidence_ref,
        payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
    )
    session.add(event)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raced = await session.scalar(
            select(ProductionEvent).where(
                ProductionEvent.job_id == job.id,
                ProductionEvent.idempotency_key == idempotency_key,
            )
        )
        if (
            raced is not None
            and raced.event_type == LOADING_RETURN_REJECTED
            and _request_event_id_from_payload(raced) == request_event_id
        ):
            return raced
        raise HTTPException(409, "Idempotency key payload tidak cocok") from exc
    await session.refresh(event)
    return event


def _pod_line_rows(lines: list[dict] | None) -> list[dict] | None:
    """Normalize an actual per-line receipt. None means the POD has no line proof."""
    if not lines:
        return None
    rows = []
    seen: set[tuple[str, str]] = set()
    for raw in lines:
        sj_line = str(raw.get("accurate_sj_line_id") or "").strip()
        so_line = str(raw.get("so_line_id") or "").strip()
        if not sj_line or not so_line:
            raise HTTPException(422, "Penerimaan per item wajib menyebut line SJ dan line SO")
        key = (sj_line, so_line)
        if key in seen:
            raise HTTPException(422, "Line SJ disebut dua kali pada POD yang sama")
        seen.add(key)
        raw_qty = raw.get("qty_physical")
        if raw_qty is None or (isinstance(raw_qty, str) and not raw_qty.strip()):
            raise HTTPException(422, "Qty penerimaan per item wajib diisi; kosong bukan nol")
        try:
            qty = Decimal(str(raw_qty))
        except Exception as exc:
            raise HTTPException(422, "Qty penerimaan per item tidak valid") from exc
        if not qty.is_finite():
            raise HTTPException(422, "Qty penerimaan per item tidak valid")
        if qty < 0:
            raise HTTPException(422, "Qty penerimaan per item tidak boleh negatif")
        row = {"accurate_sj_line_id": sj_line, "so_line_id": so_line, "qty_physical": format(qty, "f")}
        if qty == 0:
            row["explicit_zero"] = True
        rows.append(row)
    return rows


async def _loaded_sj_lines(session: AsyncSession, job_id: int, sj_id: str) -> dict[tuple[str, str], dict]:
    """Net loaded qty and official document qty per SJ line, from Loading events only."""
    rows = (
        await session.scalars(
            select(ProductionEvent).where(
                ProductionEvent.job_id == job_id,
                ProductionEvent.accurate_sj_id == sj_id,
                ProductionEvent.event_type.in_([LOADING_EVENT, LOADING_CANCEL_EVENT]),
            )
        )
    ).all()
    out: dict[tuple[str, str], dict] = {}
    for ev in rows:
        sj_line = (ev.accurate_sj_line_id or "").strip()
        so_line = (ev.so_line_id or "").strip()
        if not sj_line or not so_line:
            continue
        slot = out.setdefault((sj_line, so_line), {"loaded": Decimal(0), "document_qty": None})
        qty = Decimal(ev.qty_physical or 0)
        if ev.event_type == LOADING_EVENT:
            slot["loaded"] += qty
            raw = None
            try:
                raw = json.loads(ev.payload_json or "{}").get("authorized_base")
            except ValueError:
                raw = None
            if raw is not None:
                slot["document_qty"] = Decimal(str(raw))
        else:
            slot["loaded"] -= qty
    return out


async def record_pod(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    accurate_sj_id: str,
    qty_physical: Decimal,
    idempotency_key: str,
    receiver_name: str,
    attachment_ids: dict[str, int],
    evidence_ref: str | None = None,
    lines: list[dict] | None = None,
) -> ProductionEvent:
    """Confirm POD with four verified private attachments (photos + signatures).

    Legacy single evidence_ref is retained only as an audit note when provided —
    it never substitutes for the four attachment requirements.
    Historical POD rows without attachments remain readable and are not relabeled.
    """
    from app.services.production.lifecycle import require_job_active

    require_job_active(job)
    _require(user, P.DELIVERY_MANAGE)
    _branch(user, job.branch_id)
    receiver_name = (receiver_name or "").strip()
    if len(receiver_name) < 2:
        raise HTTPException(422, "Nama penerima minimal 2 karakter")
    sj = (accurate_sj_id or "").strip()
    if not sj:
        raise HTTPException(422, "Identitas SJ Accurate wajib")

    # Idempotent replay — do not rebind attachments, invent a second POD, or rewrite a stored receipt.
    line_rows = _pod_line_rows(lines)
    if line_rows is not None and sum(Decimal(row["qty_physical"]) for row in line_rows) != qty_physical:
        raise HTTPException(422, "Jumlah qty per item harus sama dengan qty POD")
    existing = await session.scalar(
        select(ProductionEvent).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.event_type != "pod" or (existing.accurate_sj_id or "") != sj or Decimal(existing.qty_physical or 0) != qty_physical:
            raise HTTPException(409, "Idempotency key duplikat")
        try:
            stored_lines = json.loads(existing.payload_json or "{}").get("lines")
        except ValueError:
            stored_lines = None
        if (stored_lines or None) != (line_rows or None):
            raise HTTPException(409, "Idempotency key dipakai untuk penerimaan lain")
        return existing

    cancelled = await session.scalar(
        select(func.count())
        .select_from(ProductionEvent)
        .where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "sj_cancelled",
            ProductionEvent.accurate_sj_id == sj,
        )
    )
    if int(cancelled or 0) > 0:
        raise HTTPException(409, "SJ sudah dibatalkan; gunakan SJ aktif")
    # Serialize POD against Loading cancel under the same job lock.
    locked = await session.scalar(
        select(ProductionJob)
        .where(ProductionJob.id == job.id)
        .with_for_update()
    )
    if locked is None:
        raise HTTPException(404, "Production job tidak ditemukan")

    # Re-verify SJ at POD time — never rely solely on prior loading snapshot.
    loading_row = await session.scalar(
        select(ProductionEvent)
        .where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == LOADING_EVENT,
            ProductionEvent.accurate_sj_id == sj,
        )
        .order_by(ProductionEvent.id.desc())
        .limit(1)
    )
    if loading_row is None:
        raise HTTPException(409, "POD tidak boleh bypass Loading")
    if (loading_row.accurate_sj_number or "").strip():
        from app.services.accurate_evidence import require_valid_sj

        await require_valid_sj(
            accurate_sj_id=sj,
            accurate_sj_number=loading_row.accurate_sj_number,
            expected_so_number=job.accurate_so_number,
            expected_branch_id=job.branch_id,
        )
    loaded_lines = await _loaded_sj_lines(session, job.id, sj)
    active = {key: slot for key, slot in loaded_lines.items() if slot["loaded"] > 0}
    if len(active) > 1 and line_rows is None:
        raise HTTPException(422, "POD multi-item wajib qty aktual setiap item SJ")
    if len(active) > 1 and line_rows is not None:
        got = {(row["accurate_sj_line_id"], row["so_line_id"]) for row in line_rows}
        if got != set(active):
            raise HTTPException(422, "Setiap item SJ yang sudah di-loading wajib punya qty penerimaan")
    loaded = await _net_confirmed_loading_sum(
        session, job.id, accurate_sj_id=sj
    )
    already_pod = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "pod",
            ProductionEvent.accurate_sj_id == sj,
        )
    )
    remaining = loaded - Decimal(already_pod or 0)
    if loaded <= 0:
        raise HTTPException(409, "POD tidak boleh bypass Loading")
    if qty_physical <= 0 or qty_physical > remaining:
        raise HTTPException(409, "Qty POD tidak valid terhadap sisa Loading SJ")
    if line_rows is not None:
        for row in line_rows:
            slot = loaded_lines.get((row["accurate_sj_line_id"], row["so_line_id"]))
            qty = Decimal(row["qty_physical"])
            if slot is None or slot["loaded"] <= 0:
                raise HTTPException(409, "Line penerimaan tidak ada pada Loading SJ ini")
            if qty > slot["loaded"]:
                raise HTTPException(409, "Qty penerimaan item melebihi loading line")
            if slot["document_qty"] is not None and qty > slot["document_qty"]:
                raise HTTPException(409, "Qty penerimaan item melebihi qty dokumen SJ")

    from app.services.production import attachments as attach_svc

    bound = await attach_svc.validate_unbound_pod_attachments(
        session,
        job=job,
        accurate_sj_id=sj,
        attachment_ids=attachment_ids,
    )
    # Compact audit pointer — not a substitute for attachment rows.
    note = evidence_ref.strip() if evidence_ref and evidence_ref.strip() else None
    attach_map = {p: bound[p].id for p in sorted(bound)}
    event = ProductionEvent(
        job_id=job.id,
        event_type="pod",
        qty_physical=qty_physical,
        accurate_sj_id=sj,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
        evidence_ref=note
        or ("pod_attachments:" + ",".join(f"{k}:{v}" for k, v in attach_map.items())),
        reason=f"receiver:{receiver_name.strip()}",
        payload_json=json.dumps(
            {"attachments": attach_map, **({"lines": line_rows} if line_rows else {})},
            separators=(",", ":"),
        ),
    )
    session.add(event)
    try:
        await session.flush()
        await attach_svc.bind_attachments_to_event(session, bound, event.id)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Idempotency key duplikat") from exc
    await session.refresh(event)
    return event


async def tracking_timeline(
    session: AsyncSession, user: User, job: ProductionJob
) -> list[ProductionEvent]:
    _require(user, P.TRACKING_READ)
    _branch(user, job.branch_id)
    rows = (
        await session.scalars(
            select(ProductionEvent)
            .where(ProductionEvent.job_id == job.id)
            .order_by(ProductionEvent.created_at.asc(), ProductionEvent.id.asc())
        )
    ).all()
    return list(rows)


async def find_job_by_so(
    session: AsyncSession, user: User, so_number: str
) -> ProductionJob | None:
    """Read-only lookup of the active job — never creates; never returns cancelled."""
    _require(user, P.JOB_READ)
    job = await find_active_job_by_so(session, so_number)
    if job is None:
        return None
    _branch(user, job.branch_id)
    return job


def _try_authorized_sj_pcs(line: dict) -> Decimal | None:
    """Return verified SJ-line PCS or None — never invent a quantity."""
    try:
        return _authorized_base_qty(line)
    except HTTPException:
        return None


async def resolve_loading_line_authority(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    accurate_sj_id: str,
    accurate_sj_number: str,
    accurate_sj_line_id: str,
    so_line_id: str,
) -> dict:
    """SJ-line Loading authority row for UI. Soft on gateway; UNKNOWN if unverified."""
    _require(user, P.JOB_READ)
    _branch(user, job.branch_id)
    from app.services.accurate_evidence import (
        require_valid_sj,
        resolve_sj_loading_line,
    )

    sj_id = (accurate_sj_id or "").strip()
    sj_no = (accurate_sj_number or "").strip() or sj_id
    sj_line = (accurate_sj_line_id or "").strip()
    so_line = (so_line_id or "").strip()
    if not sj_id or not sj_line or not so_line:
        raise HTTPException(422, "Identitas SJ / SJ-line / SO-line wajib")

    confirmed = await _sum_event_qty(
        session,
        job.id,
        LOADING_EVENT,
        accurate_sj_id=sj_id,
        accurate_sj_line_id=sj_line,
        so_line_id=so_line,
    )
    cancelled = await _sum_event_qty(
        session,
        job.id,
        LOADING_CANCEL_EVENT,
        accurate_sj_id=sj_id,
        accurate_sj_line_id=sj_line,
        so_line_id=so_line,
    )
    net = confirmed - cancelled
    if net < 0:
        net = Decimal("0")

    qty_sj: Decimal | None = None
    verification = "UNKNOWN"
    note = None
    try:
        evidence = await require_valid_sj(
            accurate_sj_id=sj_id,
            accurate_sj_number=sj_no,
            expected_so_number=job.accurate_so_number,
            expected_branch_id=job.branch_id,
        )
        if evidence.get("verified") and evidence.get("mode") != "test_skip":
            line = resolve_sj_loading_line(
                evidence,
                accurate_sj_line_id=sj_line,
                so_line_id=so_line,
            )
            qty_sj = _try_authorized_sj_pcs(line)
            if qty_sj is not None:
                verification = "VERIFIED"
            else:
                note = "Qty/unit_ratio SJ line tidak valid"
        else:
            note = "Verifikasi SJ Accurate tidak tersedia"
    except HTTPException as exc:
        note = str(exc.detail)

    remaining = None if qty_sj is None else max(Decimal("0"), qty_sj - net)
    readiness, po_qty, _gap = await _physical_readiness_qty(session, job.id, so_line)
    loaded_line = await _net_confirmed_loading_sum(session, job.id, so_line_id=so_line)
    pack_left = None if readiness is None else max(Decimal("0"), readiness - loaded_line)
    if po_qty is not None and pack_left is not None:
        pack_left = min(pack_left, max(Decimal("0"), po_qty - loaded_line))
    available = None
    if remaining is not None and pack_left is not None:
        available = min(remaining, pack_left) if ENFORCE_LOADING_PACKING_CAP else remaining
    elif remaining is not None and not ENFORCE_LOADING_PACKING_CAP:
        available = remaining

    def _pcs_str(value: Decimal) -> str:
        integral = value.to_integral_value()
        if value == integral:
            return str(integral)
        return format(value, "f")

    return {
        "accurate_sj_id": sj_id,
        "accurate_sj_number": sj_no,
        "accurate_sj_line_id": sj_line,
        "so_line_id": so_line,
        "verification": verification,
        "qty_sj_pcs": _pcs_str(qty_sj) if qty_sj is not None else None,
        "loading_confirmed": _pcs_str(confirmed),
        "loading_cancelled": _pcs_str(cancelled),
        "loading_net": _pcs_str(net),
        "remaining_loading": _pcs_str(remaining) if remaining is not None else None,
        "packing_cap_enforced": ENFORCE_LOADING_PACKING_CAP,
        "packed_qty": _pcs_str(readiness) if readiness is not None else None,
        "loaded_qty_line": _pcs_str(loaded_line),
        "loading_available": _pcs_str(available) if available is not None else None,
        "actions_enabled": verification == "VERIFIED",
        "note": note,
    }


async def _loading_line_authority_for_events(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    events: list[ProductionEvent],
) -> list[dict]:
    keys: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for ev in events:
        sj_id = (ev.accurate_sj_id or "").strip()
        sj_line = (ev.accurate_sj_line_id or "").strip()
        so_line = (ev.so_line_id or "").strip()
        if not sj_id or not sj_line or not so_line:
            continue
        sj_no = (ev.accurate_sj_number or "").strip() or sj_id
        key = (sj_id, sj_no, sj_line, so_line)
        if key in seen:
            continue
        seen.add(key)
        keys.append(key)
    rows: list[dict] = []
    for sj_id, sj_no, sj_line, so_line in keys:
        rows.append(
            await resolve_loading_line_authority(
                session,
                user,
                job,
                accurate_sj_id=sj_id,
                accurate_sj_number=sj_no,
                accurate_sj_line_id=sj_line,
                so_line_id=so_line,
            )
        )
    return rows


async def job_board(session: AsyncSession, user: User, job: ProductionJob) -> dict:
    """Authoritative drawer payload for one selected SO/job."""
    _require(user, P.JOB_READ)
    _branch(user, job.branch_id)
    from app.models.production.prep import JobLineQty, PrepEvent, PrepState

    from app.services.production.payment_gate import effective_status
    payment_status = await effective_status(session, job.id)
    designs = (
        await session.scalars(
            select(DesignVersion)
            .where(DesignVersion.job_id == job.id)
            .order_by(DesignVersion.version_no.desc())
        )
    ).all()
    receipts = (
        await session.scalars(
            select(PaymentReceiptRef)
            .where(PaymentReceiptRef.job_id == job.id)
            .order_by(PaymentReceiptRef.id.desc())
        )
    ).all()
    bypasses = (
        await session.scalars(
            select(PaymentBypass)
            .where(PaymentBypass.job_id == job.id)
            .order_by(PaymentBypass.id.desc())
        )
    ).all()
    assignments = (
        await session.scalars(
            select(ScheduleAssignment)
            .where(ScheduleAssignment.job_id == job.id)
            .order_by(ScheduleAssignment.id.asc())
        )
    ).all()
    samples = (
        await session.scalars(
            select(SampleVersion)
            .where(SampleVersion.job_id == job.id)
            .order_by(SampleVersion.version_no.desc())
        )
    ).all()
    prep_states = (
        await session.scalars(
            select(PrepState).where(PrepState.job_id == job.id)
        )
    ).all()
    prep_events = (
        await session.scalars(
            select(PrepEvent)
            .where(PrepEvent.job_id == job.id)
            .order_by(PrepEvent.id.desc())
            .limit(50)
        )
    ).all()
    lines = (
        await session.scalars(
            select(JobLineQty).where(JobLineQty.job_id == job.id)
        )
    ).all()
    events = (
        await session.scalars(
            select(ProductionEvent)
            .where(ProductionEvent.job_id == job.id)
            .order_by(ProductionEvent.created_at.asc(), ProductionEvent.id.asc())
        )
    ).all()
    payload = {
        "job": {
            "id": job.id,
            "accurate_so_number": job.accurate_so_number,
            "accurate_id": job.accurate_id,
            "branch_id": job.branch_id,
            "customer_name": job.customer_name,
            "buffer_stock": job.buffer_stock,
            "urgent_state": job.urgent_state,
            "design_status": job.design_status,
            "payment_status": payment_status,
            "production_approval_status": payment_status,
            "payment_review_required": bool(getattr(job, "payment_review_required", False)),
            "sample_status": job.sample_status,
            "processing_status": job.processing_status,
            "lifecycle_status": job.lifecycle_status or "active",
            "cancelled_at": job.cancelled_at.isoformat() if job.cancelled_at else None,
            "cancel_reason": job.cancel_reason,
            "cancel_gate": job.cancel_gate,
        },
        "design_versions": [
            {
                "id": d.id,
                "version_no": d.version_no,
                "file_name": d.file_name,
                "so_line_id": d.so_line_id,
                "status": d.status,
                "bypass": d.bypass,
                "customer_approval": d.customer_approval,
                "decision_reason": d.decision_reason,
            }
            for d in designs
        ],
        "payment_receipts": [
            {
                "id": r.id,
                "accurate_receipt_id": r.accurate_receipt_id,
                "accurate_receipt_number": r.accurate_receipt_number,
                "amount": str(r.amount) if r.amount is not None else None,
                "paid_at": r.paid_at.isoformat() if getattr(r, "paid_at", None) else None,
                "evidence_verified": bool(r.evidence_verified),
                "status": r.status,
                "recorded_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in receipts
        ],
        "payment_bypasses": [
            {
                "id": b.id,
                "reason": b.reason,
                "active": b.active,
                "gate_before": getattr(b, "gate_before", None),
                "idempotency_key": getattr(b, "idempotency_key", None),
                "authorized_by": b.authorized_by,
                "created_at": b.created_at.isoformat() if b.created_at else None,
                "revoke_reason": b.revoke_reason,
                "revoked_at": b.revoked_at.isoformat() if b.revoked_at else None,
            }
            for b in bypasses
        ],
        "assignments": [
            {
                "id": a.id,
                "so_line_id": a.so_line_id,
                "color_pass": a.color_pass,
                "operator_name": a.operator_name,
                "operator_user_id": a.operator_user_id,
                "machine_name": a.machine_name,
                "work_date": str(a.work_date),
                "qty_planned": str(a.qty_planned),
                "qty_confirmed": str(a.qty_confirmed),
                "qty_cancelled_remaining": str(a.qty_cancelled_remaining),
                "status": a.status,
                "location_provenance": a.location_provenance,
            }
            for a in assignments
        ],
        "samples": [
            {
                "id": s.id,
                "version_no": s.version_no,
                "file_name": s.file_name,
                "status": s.status,
                "assignment_id": s.assignment_id,
            }
            for s in samples
        ],
        "prep_states": [
            {
                "id": p.id,
                "so_line_id": p.so_line_id,
                "role": p.role,
                "qty": str(p.qty),
                "evidence_ref": p.evidence_ref,
                "screen_size": getattr(p, "screen_size", None),
                "assignment_id": p.assignment_id,
            }
            for p in prep_states
        ],
        "prep_events": [
            {
                "id": e.id,
                "role": e.role,
                "event_type": e.event_type,
                "so_line_id": e.so_line_id,
                "qty_before": str(e.qty_before),
                "qty_after": str(e.qty_after),
                "evidence_ref": e.evidence_ref,
                "screen_size": getattr(e, "screen_size", None),
            }
            for e in prep_events
        ],
        "job_lines": [
            {
                "so_line_id": ln.so_line_id,
                "accurate_item_id": ln.accurate_item_id,
                "po_qty": str(ln.po_qty),
                "production_process": ln.production_process or "unknown",
                "accurate_qty": str(ln.source_qty) if ln.source_qty is not None else None,
                "drift_detected_at": ln.drift_detected_at.isoformat() if ln.drift_detected_at else None,
                "drift_acknowledged": ln.source_qty is not None
                and any(
                    e.event_type == "qty_drift_ack"
                    and e.so_line_id == ln.so_line_id
                    and str(ln.source_qty) in (e.payload_json or "")
                    for e in events
                ),
                "line_status": ln.line_status or "active",
                "revision_note": ln.revision_note,
            }
            for ln in lines
        ],
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "qty_physical": str(e.qty_physical)
                if e.qty_physical is not None
                else None,
                "qty_pass_ops": str(e.qty_pass_ops)
                if e.qty_pass_ops is not None
                else None,
                "assignment_id": e.assignment_id,
                "so_line_id": e.so_line_id,
                "color_pass": e.color_pass,
                "lot_code": e.lot_code,
                "accurate_sj_id": e.accurate_sj_id,
                "accurate_sj_number": e.accurate_sj_number,
                "accurate_sj_line_id": e.accurate_sj_line_id,
                "actor_user_id": e.actor_user_id,
                "idempotency_key": e.idempotency_key,
                "payload_json": e.payload_json,
                "evidence_ref": e.evidence_ref,
                "reason": e.reason,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
        "sj_line_authority": await _loading_line_authority_for_events(
            session, user, job, list(events)
        ),
    }
    from app.authorization.workflow import redact_board
    return redact_board(user,payload)



# ---- Team tasks read-model (Slice 1H) ----

_TASK_META = {
    "design_upload": {
        "role": "Designer",
        "label": "Upload Design",
        "verb": "Upload desain",
        "group": "design_upload",
    },
    "design_approve": {
        "role": "Designer",
        "label": "Approval Design",
        "verb": "Sahkan desain",
        "group": "design_approve",
    },
    "schedule": {
        "role": "Kepala Produksi",
        "label": "Penjadwalan",
        "verb": "Atur jadwal",
        "group": "schedule",
    },
    "screen": {
        "role": "Screener",
        "label": "Screen",
        "verb": "Input screen",
        "group": "screen",
    },
    "prepare": {
        "role": "Helper",
        "label": "Prepare Cup",
        "verb": "Input cup siap",
        "group": "prepare",
    },
    "sample": {
        "role": "Operator",
        "label": "Upload Sampel Cetak",
        "verb": "Upload sampel",
        "group": "sample",
    },
    "sample_approve": {
        "role": "Operator",
        "label": "Approval Sampel Cetak",
        "verb": "Approve sampel",
        "group": "sample_approve",
    },
    "print": {
        "role": "Operator",
        "label": "Konfirmasi Qty Cetak",
        "verb": "Konfirmasi cetak",
        "group": "print",
    },
    "packing": {
        "role": "Helper",
        "label": "Packing",
        "verb": "Input packing",
        "group": "packing",
    },
    "stockprep": {
        "role": "Helper",
        "label": "Persiapan Barang Non-Cetak",
        "verb": "Siapkan barang",
        "group": "stockprep",
    },
    "stockpack": {
        "role": "Helper",
        "label": "Packing Barang Non-Cetak",
        "verb": "Konfirmasi packing",
        "group": "stockpack",
    },
    "loading": {
        "role": "Driver",
        "label": "Loading",
        "verb": "Konfirmasi loading SJ",
        "group": "loading",
    },
    "delivery": {
        "role": "Driver",
        "label": "Pengiriman",
        "verb": "Konfirmasi POD",
        "group": "delivery",
    },
}


def _task_qty_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f") if value != value.to_integral_value() else str(int(value))


def _loading_readiness_rows(lines: list, events: list) -> list[dict]:
    """One loading status per SO line. Packing is the ready quantity. Missing SJ stays null."""
    rows: list[dict] = []
    for ln in lines:
        process = (getattr(ln, "production_process", None) or "").strip()
        lid = str(getattr(ln, "so_line_id", "") or "").strip()
        po = getattr(ln, "po_qty", None)
        packed_events = [
            e
            for e in events
            if lid
            and getattr(e, "so_line_id", None) == lid
            and getattr(e, "event_type", None) in PACKING_EVENT_TYPES
        ]
        packed = sum(
            (Decimal(getattr(e, "qty_physical", 0) or 0) for e in packed_events),
            Decimal("0"),
        )
        gross = sum(
            (
                Decimal(getattr(e, "qty_physical", 0) or 0)
                for e in events
                if lid
                and getattr(e, "so_line_id", None) == lid
                and getattr(e, "event_type", None) == LOADING_EVENT
            ),
            Decimal("0"),
        )
        cancelled = sum(
            (
                Decimal(getattr(e, "qty_physical", 0) or 0)
                for e in events
                if lid
                and getattr(e, "so_line_id", None) == lid
                and getattr(e, "event_type", None) == LOADING_CANCEL_EVENT
            ),
            Decimal("0"),
        )
        loaded: Decimal | None
        if cancelled > gross:
            loaded = None
        else:
            loaded = gross - cancelled
        sj_remaining = _sj_remaining_for_line(events, lid) if lid else None
        status = "Belum terverifikasi"
        ready: Decimal | None = None
        if process in {"print", "non_print"} and lid and loaded is not None:
            if not packed_events:
                status = "Menunggu Packing"
            elif loaded > packed:
                status = "Belum terverifikasi"
            elif loaded == 0 and packed > 0:
                status = "Siap Loading"
                ready = packed
            elif 0 < loaded < packed:
                status = "Loading Parsial"
                ready = packed - loaded
            elif packed > 0 and loaded == packed:
                status = "Sudah Loading"
                ready = Decimal("0")
        rows.append(
            {
                "so_line_id": lid or None,
                "production_process": process or None,
                "status": status,
                "po_qty": _task_qty_text(Decimal(po)) if po is not None else None,
                "packed_qty": _task_qty_text(packed) if packed_events else None,
                "loaded_qty": _task_qty_text(loaded) if loaded is not None and lid else None,
                "ready_qty": _task_qty_text(ready),
                "sj_remaining_qty": _task_qty_text(sj_remaining),
            }
        )
    return rows


def _sj_remaining_for_line(events: list, so_line_id: str) -> Decimal | None:
    """Remaining authorized SJ qty already tied to this SO line. No SJ evidence stays unknown."""
    buckets: dict[tuple[str, str], dict] = {}
    for ev in events:
        if getattr(ev, "so_line_id", None) != so_line_id:
            continue
        kind = getattr(ev, "event_type", None)
        if kind not in {LOADING_EVENT, LOADING_CANCEL_EVENT}:
            continue
        sj = str(getattr(ev, "accurate_sj_id", "") or "").strip()
        sj_line = str(getattr(ev, "accurate_sj_line_id", "") or "").strip()
        if not sj or not sj_line:
            return None
        slot = buckets.setdefault(sj, {}).setdefault(
            sj_line, {"auth": None, "net": Decimal("0")}
        )
        qty = Decimal(getattr(ev, "qty_physical", 0) or 0)
        if kind == LOADING_EVENT:
            raw = getattr(ev, "payload_json", None) or ""
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return None
            if not isinstance(payload, dict) or payload.get("authorized_base") in (None, ""):
                return None
            try:
                auth = Decimal(str(payload["authorized_base"]))
            except Exception:
                return None
            if slot["auth"] is not None and slot["auth"] != auth:
                return None
            slot["auth"] = auth
            slot["net"] += qty
        else:
            slot["net"] -= qty
    if not buckets:
        return None
    total = Decimal("0")
    for lines in buckets.values():
        for slot in lines.values():
            if slot["auth"] is None or slot["net"] < 0 or slot["net"] > slot["auth"]:
                return None
            total += slot["auth"] - slot["net"]
    return total


def _loading_card_state(rows: list[dict]) -> tuple[str, str | None]:
    if not rows:
        return "blocked", "Belum terverifikasi"
    statuses = [row["status"] for row in rows]
    if all(status == "Sudah Loading" for status in statuses):
        return "done", None
    if all(status == "Siap Loading" for status in statuses):
        return "actionable", None
    if all(status == "Menunggu Packing" for status in statuses):
        return "blocked", "Menunggu packing sah"
    if all(status == "Belum terverifikasi" for status in statuses):
        return "blocked", "Belum terverifikasi"
    if any(status in {"Siap Loading", "Loading Parsial", "Sudah Loading"} for status in statuses):
        return "partial", "Belum semua line siap loading"
    if any(status == "Belum terverifikasi" for status in statuses):
        return "blocked", "Belum terverifikasi"
    return "blocked", "Menunggu packing sah"


def _task_row(
    job: ProductionJob,
    kind: str,
    state: str,
    *,
    reason: str | None = None,
    so_line_id: str | None = None,
    lines: list | None = None,
) -> dict:
    meta = _TASK_META[kind]
    business_id = f"{job.accurate_so_number}::{kind}"
    if so_line_id:
        business_id = f"{business_id}::{so_line_id}"
    row = {
        "id": business_id,
        "kind": kind,
        "group": meta["group"],
        "role": meta["role"],
        "label": meta["label"],
        "verb": meta["verb"],
        "state": state,  # pending | blocked | actionable | done | partial
        "visible": True,
        "reason": reason,
        "job_id": job.id,
        "accurate_so_number": job.accurate_so_number,
        "branch_id": job.branch_id,
        "customer_name": job.customer_name,
        "so_line_id": so_line_id,
        "design_status": job.design_status,
        "payment_status": job.payment_status,
        "processing_status": job.processing_status,
    }
    if lines is not None:
        row["lines"] = lines
    return row


def derive_team_tasks_for_job(
    job: ProductionJob,
    *,
    lines: list,
    designs: list,
    assignments: list,
    prep_states: list,
    samples: list,
    events: list,
    payment_status: str | None = None,
) -> list[dict]:
    """Pure derivation of official Tugas Tim from existing V3 tables.

    Never invents payment approval from PO/processing status.
    Never auto-approves design on upload.
    Non-print-only jobs never receive screen/sample/print tasks.
    """
    has_print = any((getattr(ln, "production_process", None) or "") == "print" for ln in lines)
    has_non_print = any(
        (getattr(ln, "production_process", None) or "") == "non_print" for ln in lines
    )
    # Pure-call compatibility; DB-backed callers always pass the effective status.
    payment_status = payment_status if payment_status is not None else job.payment_status
    payment_ok = payment_status in {"approved", "bypassed"}
    design_ok = job.design_status in {"approved", "bypassed"}
    pending_design = [d for d in designs if getattr(d, "status", None) == "pending"]
    uploaded_design = [
        d
        for d in designs
        if getattr(d, "status", None) in {"pending", "approved", "superseded"}
    ]
    # Prefer explicit active rows; exclude cancelled/void.
    active_assignments = [
        a
        for a in assignments
        if str(getattr(a, "status", "active") or "active")
        not in {"cancelled", "canceled", "void"}
    ]
    has_schedule = len(active_assignments) > 0
    scheduled_line_ids = {
        str(getattr(a, "so_line_id", "") or "").strip()
        for a in active_assignments
        if str(getattr(a, "so_line_id", "") or "").strip()
    }
    line_by_id = {
        str(getattr(ln, "so_line_id", "") or "").strip(): ln
        for ln in lines
        if str(getattr(ln, "so_line_id", "") or "").strip()
    }
    # Prep READY scope = scheduled lines with canonical production_process=print only.
    # UNKNOWN / missing classification never becomes print and blocks prep tasks.
    print_scheduled_ids: set[str] = set()
    unclassified_scheduled_ids: set[str] = set()
    for lid in scheduled_line_ids:
        ln = line_by_id.get(lid)
        if ln is None:
            unclassified_scheduled_ids.add(lid)
            continue
        if str(getattr(ln, "line_status", "active") or "active") != "active":
            continue
        proc = (getattr(ln, "production_process", None) or "").strip().lower()
        if proc == "print":
            print_scheduled_ids.add(lid)
        elif proc == "non_print":
            continue
        else:
            unclassified_scheduled_ids.add(lid)

    def _prep_role_ready(role: str) -> bool:
        """READY only when every scheduled print line has qty>0 for the role."""
        if unclassified_scheduled_ids:
            return False
        if print_scheduled_ids:
            return all(
                any(
                    getattr(p, "role", None) == role
                    and str(getattr(p, "so_line_id", "") or "").strip() == lid
                    and Decimal(getattr(p, "qty", 0) or 0) > 0
                    for p in prep_states
                )
                for lid in print_scheduled_ids
            )
        # Legacy / no scheduled print lines: any evidence keeps prior behaviour.
        return any(
            getattr(p, "role", None) == role and Decimal(getattr(p, "qty", 0) or 0) > 0
            for p in prep_states
        )

    screener_done = _prep_role_ready("screener")
    helper_done = _prep_role_ready("helper")
    classification_block_reason = (
        "Klasifikasi line belum resolved (UNKNOWN/hilang): "
        + ", ".join(sorted(unclassified_scheduled_ids))
        if unclassified_scheduled_ids
        else None
    )
    pending_sample = [s for s in samples if getattr(s, "status", None) == "pending"]
    approved_sample = [
        s for s in samples if getattr(s, "status", None) in {"approved", "bypassed"}
    ]
    sample_uploaded = bool(samples)
    # Cups that entered print (pass 1 ledger) — progress signal, not pack eligibility.
    print_qty = physical_cup_qty_from_events(events)
    # Print packing becomes available after helper-verified output. It is not READY.
    required_passes = required_color_passes_from_assignments(active_assignments)
    finished_qty = eligible_verified_qty_from_events(events, required_passes)
    pack_qty = packing_qty_from_events(events)
    print_lines = [
        ln
        for ln in lines
        if (getattr(ln, "production_process", None) or "") == "print"
        and getattr(ln, "so_line_id", None)
    ]
    if print_lines:
        finished_qty = sum(
            (
                eligible_verified_qty_from_events(
                    events,
                    required_color_passes_from_assignments(
                        active_assignments, so_line_id=str(ln.so_line_id)
                    ),
                    so_line_id=str(ln.so_line_id),
                )
                for ln in print_lines
            ),
            Decimal("0"),
        )
        print_pack = sum(
            (
                packing_qty_from_events(events, so_line_id=str(ln.so_line_id))
                for ln in print_lines
            ),
            Decimal("0"),
        )
    else:
        print_pack = pack_qty

    tasks: list[dict] = []

    if has_print:
        # Upload Design — available without payment; idempotent presence.
        if design_ok or uploaded_design:
            tasks.append(_task_row(job, "design_upload", "done"))
        else:
            tasks.append(_task_row(job, "design_upload", "actionable"))

        # Approval Design — never auto-approve on upload.
        if design_ok:
            tasks.append(_task_row(job, "design_approve", "done"))
        elif pending_design:
            tasks.append(_task_row(job, "design_approve", "actionable"))
        else:
            tasks.append(
                _task_row(
                    job,
                    "design_approve",
                    "blocked",
                    reason="Menunggu file desain pending",
                )
            )

        # Penjadwalan — Siap (actionable) when payment OK; save still needs design via gates_open_for_schedule.
        if payment_ok:
            if has_schedule:
                tasks.append(_task_row(job, "schedule", "done"))
            else:
                tasks.append(
                    _task_row(
                        job,
                        "schedule",
                        "actionable",
                        reason=None
                        if design_ok
                        else "Design masih diperlukan saat simpan jadwal",
                    )
                )
        # else: not visible

        # Screen + Prepare Cup — only after valid schedule; parallel; print-classified only.
        if has_schedule:
            if classification_block_reason:
                tasks.append(
                    _task_row(
                        job,
                        "screen",
                        "blocked",
                        reason=classification_block_reason,
                    )
                )
                tasks.append(
                    _task_row(
                        job,
                        "prepare",
                        "blocked",
                        reason=classification_block_reason,
                    )
                )
            else:
                tasks.append(
                    _task_row(job, "screen", "done" if screener_done else "actionable")
                )
                tasks.append(
                    _task_row(job, "prepare", "done" if helper_done else "actionable")
                )

        # Downstream print chain — only after prep evidence on classified print lines.
        if has_schedule and screener_done and helper_done and not unclassified_scheduled_ids:
            if approved_sample:
                tasks.append(_task_row(job, "sample", "done"))
                tasks.append(_task_row(job, "sample_approve", "done"))
            elif pending_sample or sample_uploaded:
                tasks.append(_task_row(job, "sample", "done"))
                tasks.append(
                    _task_row(
                        job,
                        "sample_approve",
                        "actionable" if pending_sample else "blocked",
                        reason=None
                        if pending_sample
                        else "Menunggu sampel pending untuk approval",
                    )
                )
            else:
                tasks.append(_task_row(job, "sample", "actionable"))

            if approved_sample:
                if print_qty > 0:
                    tasks.append(_task_row(job, "print", "done"))
                else:
                    tasks.append(_task_row(job, "print", "actionable"))
                # Packing only when cups completed ALL required color passes.
                if finished_qty > 0:
                    if print_pack > 0:
                        tasks.append(_task_row(job, "packing", "done"))
                    else:
                        tasks.append(_task_row(job, "packing", "actionable"))
                elif print_qty > 0:
                    tasks.append(
                        _task_row(
                            job,
                            "packing",
                            "blocked",
                            reason="Menunggu seluruh warna/pass selesai sebelum packing",
                        )
                    )

    if has_non_print:
        # Non-print skips design, schedule, screen, sample, and print. Payment still binds.
        np_lines = [
            ln
            for ln in lines
            if (getattr(ln, "production_process", None) or "") == "non_print"
        ]
        if payment_ok:
            identified = [ln for ln in np_lines if getattr(ln, "so_line_id", None)]
            if identified:
                packed_enough = all(
                    packing_qty_from_events(events, so_line_id=str(ln.so_line_id))
                    >= Decimal(getattr(ln, "po_qty", 0) or 0)
                    for ln in identified
                )
            else:
                packed_enough = pack_qty > 0
            tasks.append(
                _task_row(job, "stockpack", "done" if packed_enough else "actionable")
            )
        else:
            tasks.append(
                _task_row(
                    job,
                    "stockpack",
                    "pending",
                    reason="Menunggu payment approved/bypassed",
                )
            )

    if has_print or has_non_print:
        # Loading follows confirmed packing for every physical line. Print output is not enough.
        load_gross = sum(
            (
                Decimal(getattr(e, "qty_physical", 0) or 0)
                for e in events
                if getattr(e, "event_type", None) == LOADING_EVENT
            ),
            Decimal("0"),
        )
        load_cancel = sum(
            (
                Decimal(getattr(e, "qty_physical", 0) or 0)
                for e in events
                if getattr(e, "event_type", None) == LOADING_CANCEL_EVENT
            ),
            Decimal("0"),
        )
        load_qty = load_gross - load_cancel
        if load_qty < 0:
            load_qty = Decimal("0")
        pod_qty = sum(
            (
                Decimal(getattr(e, "qty_physical", 0) or 0)
                for e in events
                if getattr(e, "event_type", None) == "pod"
            ),
            Decimal("0"),
        )
        compliant_pod = False
        for e in events:
            if getattr(e, "event_type", None) != "pod":
                continue
            raw = getattr(e, "payload_json", None) or ""
            if '"attachments"' in str(raw) and "pod_photo_1" in str(raw):
                compliant_pod = True
                break
        line_rows = _loading_readiness_rows(lines, events)
        card_state, card_reason = _loading_card_state(line_rows)
        if payment_ok:
            if pack_qty <= 0:
                tasks.append(
                    _task_row(
                        job,
                        "loading",
                        card_state,
                        reason=card_reason,
                        lines=line_rows,
                    )
                )
                tasks.append(
                    _task_row(
                        job,
                        "delivery",
                        "blocked",
                        reason="Menunggu Loading SJ resmi",
                    )
                )
            elif load_qty > 0:
                tasks.append(
                    _task_row(
                        job,
                        "loading",
                        card_state,
                        reason=card_reason,
                        lines=line_rows,
                    )
                )
                if compliant_pod and pod_qty > 0:
                    if pod_qty >= load_qty:
                        tasks.append(_task_row(job, "delivery", "done"))
                    else:
                        tasks.append(
                            _task_row(
                                job,
                                "delivery",
                                "actionable",
                                reason="Pengiriman parsial — sisa loading masih ada",
                            )
                        )
                else:
                    tasks.append(
                        _task_row(
                            job,
                            "delivery",
                            "actionable",
                            reason="POD wajib 2 foto + 2 TTD terverifikasi",
                        )
                    )
            else:
                tasks.append(
                    _task_row(
                        job,
                        "loading",
                        card_state,
                        reason=card_reason,
                        lines=line_rows,
                    )
                )
                tasks.append(
                    _task_row(
                        job,
                        "delivery",
                        "blocked",
                        reason="Menunggu Loading SJ resmi",
                    )
                )

    # Unknown-only: no fake print/non-print task chain — classification lives on Jadwal/Inbox.
    # (empty list on purpose)

    for task in tasks:
        task["payment_status"] = payment_status
    return tasks


async def list_payment_receipts(
    session: AsyncSession,
    user: User,
    *,
    q: str | None = None,
    payment_status: str | None = None,
    receipt_status: str | None = None,
    receipts: str | None = None,
    branch: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    review_required: bool | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict:
    """Per-PO payment monitor: one row per job (with or without receipts), read-only.

    Derived from PaymentReceiptRef/PaymentBypass through the existing payment gate; no ledger copy.
    Invoice outstanding / fully-paid settlement is intentionally null until Accurate
    receivable allocation is an Owner-approved contract.
    """
    _require(user, P.JOB_READ)
    from app.authorization.workflow import branch_allowed
    from app.services.production.payment_gate import monitor_financial_fields, status_expression

    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    # Separate subqueries so EXISTS clauses cannot auto-correlate to the outer tables and a PO
    # with many receipts stays one row.
    st = select(ProductionJob.id.label("job_id"), status_expression().label("payment_status")).subquery()
    agg = (
        select(
            PaymentReceiptRef.job_id.label("job_id"),
            func.count(PaymentReceiptRef.id).label("receipt_count"),
            func.sum(PaymentReceiptRef.amount).filter(
                PaymentReceiptRef.status == "valid",
                PaymentReceiptRef.evidence_verified.is_(True),
                PaymentReceiptRef.amount > 0,
            ).label("verified_amount"),
            func.max(PaymentReceiptRef.paid_at).label("latest_paid_at"),
            func.max(PaymentReceiptRef.created_at).label("latest_receipt_at"),
        )
        .group_by(PaymentReceiptRef.job_id)
        .subquery()
    )
    count_col = func.coalesce(agg.c.receipt_count, 0)
    branches = (await session.scalars(select(ProductionJob.branch_id).distinct())).all()
    allowed = [b for b in branches if branch_allowed(user, b)]
    if branch:
        allowed = [b for b in allowed if b == branch]
    base = (
        select(
            ProductionJob,
            st.c.payment_status,
            count_col.label("receipt_count"),
            agg.c.verified_amount,
            agg.c.latest_paid_at,
            agg.c.latest_receipt_at,
        )
        .join(st, st.c.job_id == ProductionJob.id)
        .outerjoin(agg, agg.c.job_id == ProductionJob.id)
        .where(ProductionJob.branch_id.in_(allowed or [""]))
    )
    if payment_status:
        base = base.where(st.c.payment_status == payment_status)
    if receipts == "with":
        base = base.where(count_col > 0)
    elif receipts == "without":
        base = base.where(count_col == 0)
    if receipt_status:
        base = base.where(
            select(PaymentReceiptRef.id)
            .where(PaymentReceiptRef.job_id == ProductionJob.id, PaymentReceiptRef.status == receipt_status)
            .exists()
        )
    if review_required is True:
        base = base.where(ProductionJob.payment_review_required.is_(True))
    elif review_required is False:
        base = base.where(ProductionJob.payment_review_required.is_(False))
    # Date filter uses Accurate paid_at when present, else local receipt recorded_at.
    if date_from is not None or date_to is not None:
        day_expr = func.coalesce(PaymentReceiptRef.paid_at, PaymentReceiptRef.created_at)
        date_exists = select(PaymentReceiptRef.id).where(
            PaymentReceiptRef.job_id == ProductionJob.id
        )
        if date_from is not None:
            date_exists = date_exists.where(day_expr >= date_from)
        if date_to is not None:
            date_exists = date_exists.where(day_expr <= date_to)
        base = base.where(date_exists.exists())
    term = (q or "").strip()
    if term:
        like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        base = base.where(or_(
            ProductionJob.accurate_so_number.ilike(like, escape="\\"),
            ProductionJob.customer_name.ilike(like, escape="\\"),
            select(PaymentReceiptRef.id).where(
                PaymentReceiptRef.job_id == ProductionJob.id,
                or_(
                    PaymentReceiptRef.accurate_receipt_id.ilike(like, escape="\\"),
                    PaymentReceiptRef.accurate_receipt_number.ilike(like, escape="\\"),
                ),
            ).exists(),
        ))
    total = await session.scalar(select(func.count()).select_from(base.order_by(None).subquery())) or 0
    rows = (await session.execute(
        base.order_by(ProductionJob.id.desc()).limit(page_size).offset((page - 1) * page_size)
    )).all()
    job_ids = [job.id for job, *_ in rows]
    by_job: dict[int, list] = {}
    bypass_by_job: dict[int, list] = {}
    bypassed: set[int] = set()
    if job_ids:
        for r in (await session.scalars(
            select(PaymentReceiptRef).where(PaymentReceiptRef.job_id.in_(job_ids)).order_by(PaymentReceiptRef.id.desc())
        )).all():
            by_job.setdefault(r.job_id, []).append(r)
        for b in (await session.scalars(
            select(PaymentBypass).where(PaymentBypass.job_id.in_(job_ids)).order_by(PaymentBypass.id.desc())
        )).all():
            bypass_by_job.setdefault(b.job_id, []).append(b)
            if b.active:
                bypassed.add(b.job_id)
    from app.services.production.payment_settings import bypass_enabled as settings_bypass_enabled

    bypass_on = await settings_bypass_enabled(session)
    actor_can_bypass = P.user_may_bypass_payment(user) and bypass_on
    items = []
    for job, status, count, verified, latest_paid_at, latest_receipt_at in rows:
        verified_s = str(verified) if verified is not None else None
        fin = monitor_financial_fields(verified_amount=verified_s, payment_status=status)
        latest_bypass = next((b.created_at for b in bypass_by_job.get(job.id, []) if b.active), None)
        last_parts = [t for t in (latest_paid_at, latest_receipt_at, latest_bypass, job.updated_at) if t]
        last_updated = max(last_parts).isoformat() if last_parts else None
        items.append(
            {
                "job_id": job.id,
                "so_number": job.accurate_so_number,
                "customer_name": job.customer_name,
                "branch_id": job.branch_id,
                "payment_status": status,
                "bypass_active": job.id in bypassed,
                "can_bypass": bool(actor_can_bypass and status == "pending" and job.id not in bypassed),
                "payment_review_required": bool(getattr(job, "payment_review_required", False)),
                "receipt_count": int(count),
                "verified_amount": verified_s,
                "payment_date": latest_paid_at.isoformat() if latest_paid_at else None,
                "last_updated_at": last_updated,
                **fin,
                "receipts": [
                    {
                        "receipt_id": r.id,
                        "accurate_receipt_id": r.accurate_receipt_id,
                        "accurate_receipt_number": r.accurate_receipt_number,
                        "amount": str(r.amount) if r.amount is not None else None,
                        "paid_at": r.paid_at.isoformat() if getattr(r, "paid_at", None) else None,
                        "receipt_status": r.status,
                        "evidence_verified": bool(r.evidence_verified),
                        "recorded_at": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in by_job.get(job.id, [])
                ],
                "bypasses": [
                    {
                        "bypass_id": b.id,
                        "active": b.active,
                        "reason": b.reason,
                        "gate_before": getattr(b, "gate_before", None),
                        "authorized_by": b.authorized_by,
                        "created_at": b.created_at.isoformat() if b.created_at else None,
                        "revoked_at": b.revoked_at.isoformat() if b.revoked_at else None,
                        "revoke_reason": b.revoke_reason,
                    }
                    for b in bypass_by_job.get(job.id, [])
                ],
            }
        )
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "has_more": page * page_size < total}


def _assignment_is_mine(assignment, user: User) -> bool:
    """Official id wins; legacy rows without an id match only by exact display name."""
    if assignment.operator_user_id is not None:
        return assignment.operator_user_id == user.id
    return (assignment.operator_name or "").strip().lower() == (user.display_name or "").strip().lower()


_TASK_ROLE_PERMISSIONS = {
    "Designer": (P.DESIGN_UPLOAD, P.DESIGN_APPROVE, P.DESIGN_BYPASS),
    "Screener": (P.PREP_SCREENER,),
    "Helper": (P.PREP_HELPER, P.OUTPUT_HELPER_VERIFY),
    "Operator": (P.OUTPUT_CONFIRM, P.REJECT_RECORD),
    "Driver": (P.DELIVERY_MANAGE,),
    "Kepala Produksi": (P.SCHEDULE_MANAGE,),
}


def _role_task_visible(user: User, role: str | None) -> bool:
    """A non-manager sees only tasks for roles the account is actually permitted to perform."""
    from app.authorization.workflow import legacy_allowed

    perms = _TASK_ROLE_PERMISSIONS.get(role or "")
    if perms is None:
        return True
    return any(legacy_allowed(user, (perm,)) for perm in perms)


async def list_team_tasks(
    session: AsyncSession,
    user: User,
    *,
    so_numbers: list[str] | None = None,
    sync_ensure: bool = False,
    sync_payloads: list[dict] | None = None,
) -> dict:
    """Official Tugas Tim list derived from V3 jobs (+ optional idempotent ensure_job)."""
    _require(user, P.JOB_READ)
    synced: list[str] = []
    if sync_ensure and sync_payloads:
        _require(user, P.JOB_CREATE)
        from app.authorization.workflow import branch_allowed, branch_allowed_for
        # One transaction for the whole page: any failure leaves no partial sync.
        # Rows are written in sorted SO order so concurrent syncs take unique-index
        # locks in the same order (no lock-order deadlock); the response keeps input order.
        indexed = []
        for position, payload in enumerate(sync_payloads):
            so = str(payload.get("accurate_so_number") or "").strip()
            branch_id = str(payload.get("branch_id") or "").strip()
            if so and branch_id:
                indexed.append((so, position, branch_id, payload))
        done: dict[int, str] = {}
        try:
            for so, position, branch_id, payload in sorted(indexed, key=lambda t: (t[0], t[1])):
                if not branch_allowed(user, branch_id) or not branch_allowed_for(
                    user, "job.create", branch_id
                ):
                    continue
                await ensure_job(
                    session,
                    user,
                    accurate_so_number=so,
                    branch_id=branch_id,
                    accurate_id=payload.get("accurate_id"),
                    customer_name=payload.get("customer_name"),
                    buffer_stock=payload.get("buffer_stock"),
                    urgent_state=payload.get("urgent_state"),
                    line_items=payload.get("line_items"),
                    commit=False,
                )
                done[position] = so
            await session.commit()
            synced.extend(done[k] for k in sorted(done))
        except (IntegrityError, DBAPIError) as exc:
            await session.rollback()
            # Only concurrency outcomes are retryable: unique violation from a racing
            # insert, deadlock, serialization failure. Anything else is a real fault.
            if getattr(exc.orig, "sqlstate", None) not in {"23505", "40P01", "40001"}:
                raise
            from app.core.errors import AppError
            raise AppError(
                "Sinkronisasi bersamaan terdeteksi; tidak ada data tertulis, coba lagi",
                code="sync_conflict_nothing_written",
                status_code=409,
            ) from exc
        except BaseException:
            await session.rollback()
            raise

    from app.models.production.prep import JobLineQty, PrepState

    q = select(ProductionJob)
    if so_numbers:
        cleaned = [s.strip() for s in so_numbers if s and str(s).strip()]
        if cleaned:
            q = q.where(ProductionJob.accurate_so_number.in_(cleaned))
    jobs = (await session.scalars(q.order_by(ProductionJob.id.asc()))).all()
    from app.authorization.workflow import branch_allowed
    jobs = [j for j in jobs if branch_allowed(user, j.branch_id)]

    from app.services.production.payment_gate import effective_statuses
    payment_states = await effective_statuses(session, [job.id for job in jobs])
    from app.authorization.workflow import legacy_allowed

    sees_all = legacy_allowed(user, (P.SCHEDULE_MANAGE,))
    tasks: list[dict] = []
    job_summaries: list[dict] = []
    for job in jobs:
        lines = (
            await session.scalars(
                select(JobLineQty).where(JobLineQty.job_id == job.id)
            )
        ).all()
        designs = (
            await session.scalars(
                select(DesignVersion)
                .where(DesignVersion.job_id == job.id)
                .order_by(DesignVersion.version_no.desc())
            )
        ).all()
        assignments = (
            await session.scalars(
                select(ScheduleAssignment).where(ScheduleAssignment.job_id == job.id)
            )
        ).all()
        prep_states = (
            await session.scalars(
                select(PrepState).where(PrepState.job_id == job.id)
            )
        ).all()
        samples = (
            await session.scalars(
                select(SampleVersion).where(SampleVersion.job_id == job.id)
            )
        ).all()
        events = (
            await session.scalars(
                select(ProductionEvent).where(ProductionEvent.job_id == job.id)
            )
        ).all()
        derived = derive_team_tasks_for_job(
            job,
            lines=list(lines),
            designs=list(designs),
            assignments=list(assignments),
            prep_states=list(prep_states),
            samples=list(samples),
            events=list(events),
            payment_status=payment_states[job.id],
        )
        if not sees_all:
            derived = [t for t in derived if _role_task_visible(user, t.get("role"))]
            derived = [
                t
                for t in derived
                if t.get("role") != "Operator"
                or any(
                    _assignment_is_mine(a, user)
                    and (not t.get("so_line_id") or a.so_line_id == t.get("so_line_id"))
                    for a in assignments
                )
            ]
        tasks.extend(derived)
        job_summaries.append(
            {
                "id": job.id,
                "accurate_so_number": job.accurate_so_number,
                "branch_id": job.branch_id,
                "customer_name": job.customer_name,
                "design_status": job.design_status,
                "payment_status": payment_states[job.id],
                "processing_status": job.processing_status,
                "has_print": any(
                    (ln.production_process or "") == "print" for ln in lines
                ),
                "has_non_print": any(
                    (ln.production_process or "") == "non_print" for ln in lines
                ),
                "qty_drift": [
                    {
                        "so_line_id": ln.so_line_id,
                        "po_qty": str(ln.po_qty),
                        "accurate_qty": str(ln.source_qty),
                    }
                    for ln in lines
                    if ln.source_qty is not None
                ],
            }
        )

    return {
        "source": "v3_official",
        "tasks": tasks,
        "jobs": job_summaries,
        "synced_so_numbers": synced,
        "count": len(tasks),
    }
