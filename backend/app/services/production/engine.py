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
    """Create or refresh job. Classifications stay null/unknown unless explicit.

    commit=False leaves the write pending in the caller's transaction (bulk sync).
    """
    from app.services.production.prep import sync_job_lines_from_so_detail

    _require(user, P.JOB_CREATE)
    _branch(user, branch_id)
    buffer_v = _coerce_buffer_stock(buffer_stock)
    urgent_v = _coerce_urgent_state(urgent_state)
    existing = await session.scalar(
        select(ProductionJob).where(
            ProductionJob.accurate_so_number == accurate_so_number
        )
    )
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
        if line_items:
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
    )
    session.add(job)
    await session.flush()
    if line_items:
        await sync_job_lines_from_so_detail(session, job, line_items)
    # Keep inbox WO mirror in sync.
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
        result.update(verified=True, amount=str(row.amount), live_verified=evidence["live_verified"],
                      source=evidence.get("source"), payload_status=evidence["payload_status"])
    await session.flush()
    await _refresh_payment_gate(session, job)
    result.update(payment_status=job.payment_status, before=before)
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
        if existing.status == "valid" and not existing.evidence_verified:
            existing.amount = evidence["amount"]
            existing.evidence_verified = True
            session.add(ProductionEvent(
                job_id=job.id, event_type="payment_receipt_reverified",
                idempotency_key=f"pay-reverified:{existing.id}", actor_user_id=user.id,
                payload_json=json.dumps({"receipt_id": existing.id}),
            ))
        await session.flush()
        # Do not revive invalidated evidence on an idempotent replay.
        await _refresh_payment_gate(session, job)
        await session.commit()
        return existing
    row = PaymentReceiptRef(
        job_id=job.id, accurate_receipt_id=rid,
        accurate_receipt_number=evidence.get("accurate_receipt_number"),
        amount=evidence["amount"], evidence_verified=True,
        idempotency_key=idempotency_key, status="valid", recorded_by=user.id,
        note=(note or "") + f" | evidence:{evidence['mode']}:{evidence['payload_status']}",
    )
    session.add(row)
    try:
        await session.flush()
        await _refresh_payment_gate(session, job)
        await _mark_terproses(session, job)
        session.add(ProductionEvent(
            job_id=job.id, event_type="payment_receipt_verified",
            idempotency_key=f"pay-receipt:{row.id}", actor_user_id=user.id,
            payload_json=json.dumps({"receipt_id": row.id, "accurate_receipt_id": rid,
                                     "amount": str(row.amount)}),
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
) -> PaymentBypass:
    _require(user, P.PAYMENT_BYPASS)
    job = await _lock_payment_job(session, user, job)
    if not reason.strip():
        raise HTTPException(422, "Bypass payment memerlukan alasan")
    row = PaymentBypass(
        job_id=job.id,
        reason=reason.strip(),
        authorized_by=user.id,
        active=True,
    )
    session.add(row)
    await session.flush()
    await _refresh_payment_gate(session, job)
    await _mark_terproses(session, job)
    session.add(
        ProductionEvent(
            job_id=job.id,
            event_type="payment_bypass_authorized",
            idempotency_key=(
                f"pay-bypass:{job.id}:{user.id}:"
                f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
            ),
            actor_user_id=user.id,
            reason=reason.strip(),
            payload_json=(
                f'{{"permission":"{P.PAYMENT_BYPASS}","actor_user_id":{user.id}}}'
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
    row.active = False
    row.revoked_by = user.id
    row.revoke_reason = reason
    row.revoked_at = datetime.now(UTC)
    await session.flush()
    await _refresh_payment_gate(session, job)
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
            payload_json=(
                f'{{"bypass_id":{row.id},"permission":"{P.PAYMENT_REVOKE}",'
                f'"actor_user_id":{user.id}}}'
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
    row.status = "invalidated"
    row.note = (row.note or "") + f" | invalidated: {reason}"
    await session.flush()
    await _refresh_payment_gate(session, job)
    # Append-only audit event (never silent overwrite).
    session.add(
        ProductionEvent(
            job_id=job.id,
            event_type="payment_receipt_invalidated",
            idempotency_key=f"pay-invalidate:{row.id}:{int(datetime.now(UTC).timestamp())}",
            actor_user_id=user.id,
            reason=reason.strip(),
            payload_json=(
                f'{{"receipt_id":{row.id},"accurate_receipt_id":'
                f'"{row.accurate_receipt_id}"}}'
            ),
        )
    )
    await session.commit()
    await session.refresh(row)
    return row


# ---- Schedule ----


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
) -> ScheduleAssignment:
    _require(user, P.SCHEDULE_MANAGE)
    job = await _lock_payment_job(session, user, job)
    await _refresh_payment_gate(session, job)
    await gates_open_for_schedule(job, session)
    if qty_planned <= 0:
        raise HTTPException(422, "Qty rencana harus > 0")
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
    row = await session.get(ScheduleAssignment, assignment_id)
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
) -> ScheduleAssignment:
    _require(user, P.SCHEDULE_MANAGE)
    src = await session.get(ScheduleAssignment, assignment_id)
    if src is None:
        raise HTTPException(404, "Assignment tidak ditemukan")
    job = await get_job(session, src.job_id)
    _branch(user, job.branch_id)
    remaining = src.qty_planned - src.qty_confirmed - src.qty_cancelled_remaining
    if remaining <= 0:
        raise HTTPException(409, "Tidak ada sisa untuk dipindahkan")
    src.qty_cancelled_remaining = src.qty_cancelled_remaining + remaining
    src.status = "transferred"
    new_row = ScheduleAssignment(
        job_id=job.id,
        so_line_id=src.so_line_id,
        product_id=src.product_id,
        color_pass=src.color_pass,
        operator_name=operator_name,
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
        from app.models.production.prep import PrepState

        screen = await session.scalar(
            select(func.coalesce(func.sum(PrepState.qty), 0)).where(
                PrepState.job_id == job.id, PrepState.role == "screener"
            )
        )
        prepared = await session.scalar(
            select(func.coalesce(func.sum(PrepState.qty), 0)).where(
                PrepState.job_id == job.id, PrepState.role == "helper"
            )
        )
        if Decimal(screen or 0) <= 0 or Decimal(prepared or 0) <= 0:
            raise HTTPException(
                409, "Sample approval membutuhkan screener & helper prep > 0"
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
    _require(user, P.OUTPUT_CONFIRM)
    _branch(user, job.branch_id)
    assignment = await session.get(ScheduleAssignment, assignment_id)
    if assignment is None or assignment.job_id != job.id:
        raise HTTPException(404, "Assignment tidak valid")
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
        job_id=job.id,
        assignment_id=assignment_id,
        event_type="output_confirmed",
        so_line_id=assignment.so_line_id,
        color_pass=color_pass,
        lot_code=lot_code,
        qty_physical=qty_physical,
        qty_pass_ops=qty_pass_ops if qty_pass_ops is not None else qty_physical,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
        evidence_ref=evidence_ref,
    )
    session.add(event)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Idempotency key duplikat / concurrent submit") from exc
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
    _require(user, P.REJECT_VERIFY)
    src = await session.get(ProductionEvent, event_id)
    if src is None or src.event_type != "reject":
        raise HTTPException(404, "Reject event tidak ditemukan")
    job = await get_job(session, src.job_id)
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
    _require(user, P.OUTPUT_CONFIRM)
    _branch(user, job.branch_id)
    if not reason.strip():
        raise HTTPException(422, "Koreksi memerlukan alasan")
    if qty_physical_delta == 0:
        raise HTTPException(422, "Delta koreksi tidak boleh 0")
    src = await session.get(ProductionEvent, source_event_id)
    if src is None or src.job_id != job.id or src.event_type != "output_confirmed":
        raise HTTPException(404, "Output event sumber tidak ditemukan")
    payload_json = f'{{"source_output_id":{src.id}}}'

    def _same(row: ProductionEvent) -> bool:
        return (
            row.job_id == job.id
            and row.event_type == "output_correction"
            and row.qty_physical == qty_physical_delta
            and (row.reason or "") == reason.strip()
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
        job_id=job.id,
        assignment_id=src.assignment_id,
        event_type="output_correction",
        so_line_id=src.so_line_id,
        color_pass=src.color_pass,
        lot_code=src.lot_code,
        qty_physical=qty_physical_delta,
        qty_pass_ops=qty_physical_delta,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
        reason=reason.strip(),
        payload_json=payload_json,
    )
    session.add(event)
    try:
        if src.assignment_id:
            assignment = await session.get(ScheduleAssignment, src.assignment_id)
            if assignment:
                assignment.qty_confirmed = assignment.qty_confirmed + qty_physical_delta
                if assignment.qty_confirmed < 0:
                    raise HTTPException(409, "Koreksi membuat qty confirmed negatif")
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        orig = exc.orig
        if (
            getattr(orig, "sqlstate", None) != "23505"
            or "uq_production_events_idempotency" not in str(orig)
        ):
            raise
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
    _require(user, P.OUTPUT_HELPER_VERIFY)
    _branch(user, job.branch_id)
    if qty_physical <= 0:
        raise HTTPException(422, "Qty verifikasi helper harus > 0")
    src = await session.get(ProductionEvent, source_output_event_id)
    if src is None or src.job_id != job.id or src.event_type != "output_confirmed":
        raise HTTPException(404, "Output operator sumber tidak ditemukan")
    # Operator net for this source = confirmed + corrections tied to it.
    corrections = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "output_correction",
            ProductionEvent.payload_json.contains(f'"source_output_id":{src.id}'),
        )
    )
    operator_net = Decimal(src.qty_physical or 0) + Decimal(corrections or 0)
    if operator_net < 0:
        operator_net = Decimal("0")
    already = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == HELPER_VERIFIED_EVENT,
            ProductionEvent.payload_json.contains(
                f'"source_output_event_id":{src.id}'
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
        .where(ProductionEvent.id == src.id)
        .with_for_update()
    )
    # Re-check after lock.
    already2 = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == HELPER_VERIFIED_EVENT,
            ProductionEvent.payload_json.contains(
                f'"source_output_event_id":{src.id}'
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
        "source_output_event_id": src.id,
        "assignment_id": src.assignment_id,
        "color_pass": int(src.color_pass or PHYSICAL_CUP_COLOR_PASS),
        "operator_actor_user_id": src.actor_user_id,
        "helper_actor_user_id": user.id,
        "reason": (reason or "").strip() or None,
    }
    event = ProductionEvent(
        job_id=job.id,
        assignment_id=src.assignment_id,
        event_type=HELPER_VERIFIED_EVENT,
        so_line_id=src.so_line_id,
        color_pass=src.color_pass or PHYSICAL_CUP_COLOR_PASS,
        lot_code=src.lot_code,
        qty_physical=qty_physical,
        qty_pass_ops=qty_physical,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
        evidence_ref=evidence_ref,
        reason=(reason or "").strip() or None,
        payload_json=json.dumps(payload, separators=(",", ":")),
    )
    session.add(event)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Idempotency key duplikat / concurrent verify") from exc
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
    _require(user, P.PACKING_RECORD)
    _branch(user, job.branch_id)
    if qty_physical <= 0:
        raise HTTPException(422, "Qty packing harus > 0")
    # Required passes from schedule for this SO line (default pass 1 if none).
    asg_rows = (
        await session.scalars(
            select(ScheduleAssignment).where(
                ScheduleAssignment.job_id == job.id,
                ScheduleAssignment.so_line_id == so_line_id,
            )
        )
    ).all()
    required = required_color_passes_from_assignments(asg_rows, so_line_id=so_line_id)
    # Packing authority = helper-verified pool (min across required passes).
    # Operator output alone is never packable stock. Never sum multi-color passes.
    # Loading remains independent (SJ-line PCS) — packing is monitoring only for Loading.
    pass_nets: list[Decimal] = []
    for pass_no in sorted(required):
        verified = await session.scalar(
            select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
                ProductionEvent.job_id == job.id,
                ProductionEvent.event_type.in_(list(HELPER_VERIFIED_EVENT_TYPES)),
                ProductionEvent.so_line_id == so_line_id,
                func.coalesce(ProductionEvent.color_pass, PHYSICAL_CUP_COLOR_PASS)
                == pass_no,
            )
        )
        rejected = await session.scalar(
            select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
                ProductionEvent.job_id == job.id,
                ProductionEvent.event_type.in_(list(REJECT_EVENT_TYPES)),
                ProductionEvent.so_line_id == so_line_id,
                func.coalesce(ProductionEvent.color_pass, PHYSICAL_CUP_COLOR_PASS)
                == pass_no,
            )
        )
        pass_nets.append(Decimal(verified or 0) - Decimal(rejected or 0))
    eligible = min(pass_nets) if pass_nets else Decimal("0")
    packed = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type.in_(list(PACKING_EVENT_TYPES)),
            ProductionEvent.so_line_id == so_line_id,
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
        job_id=job.id,
        event_type=CANONICAL_PACKING_EVENT,
        so_line_id=so_line_id,
        lot_code=lot_code,
        qty_physical=qty_physical,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
        evidence_ref=evidence_ref,
    )
    session.add(event)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Idempotency key duplikat") from exc
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
    """Confirm Loading against Accurate SJ line capacity only (not Packing)."""
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
    # Packing is monitoring-only — never a hard Loading cap.
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
) -> ProductionEvent:
    """Confirm POD with four verified private attachments (photos + signatures).

    Legacy single evidence_ref is retained only as an audit note when provided —
    it never substitutes for the four attachment requirements.
    Historical POD rows without attachments remain readable and are not relabeled.
    """
    _require(user, P.DELIVERY_MANAGE)
    _branch(user, job.branch_id)
    if not (receiver_name or "").strip():
        raise HTTPException(422, "POD memerlukan nama penerima")
    sj = (accurate_sj_id or "").strip()
    if not sj:
        raise HTTPException(422, "Identitas SJ Accurate wajib")

    # Idempotent replay — do not rebind attachments or invent a second POD.
    existing = await session.scalar(
        select(ProductionEvent).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.event_type != "pod":
            raise HTTPException(409, "Idempotency key duplikat")
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
        payload_json=json.dumps({"attachments": attach_map}, separators=(",", ":")),
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
    """Read-only lookup — never creates a job."""
    _require(user, P.JOB_READ)
    job = await session.scalar(
        select(ProductionJob).where(ProductionJob.accurate_so_number == so_number)
    )
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
        "packing_monitoring_only": True,
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
            "sample_status": job.sample_status,
            "processing_status": job.processing_status,
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
                "status": r.status,
            }
            for r in receipts
        ],
        "payment_bypasses": [
            {
                "id": b.id,
                "reason": b.reason,
                "active": b.active,
                "revoke_reason": b.revoke_reason,
            }
            for b in bypasses
        ],
        "assignments": [
            {
                "id": a.id,
                "so_line_id": a.so_line_id,
                "color_pass": a.color_pass,
                "operator_name": a.operator_name,
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


def _task_row(
    job: ProductionJob,
    kind: str,
    state: str,
    *,
    reason: str | None = None,
    so_line_id: str | None = None,
) -> dict:
    meta = _TASK_META[kind]
    business_id = f"{job.accurate_so_number}::{kind}"
    if so_line_id:
        business_id = f"{business_id}::{so_line_id}"
    return {
        "id": business_id,
        "kind": kind,
        "group": meta["group"],
        "role": meta["role"],
        "label": meta["label"],
        "verb": meta["verb"],
        "state": state,  # pending | blocked | actionable | done
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
    screener_done = any(
        getattr(p, "role", None) == "screener" and Decimal(getattr(p, "qty", 0) or 0) > 0
        for p in prep_states
    )
    helper_done = any(
        getattr(p, "role", None) == "helper" and Decimal(getattr(p, "qty", 0) or 0) > 0
        for p in prep_states
    )
    pending_sample = [s for s in samples if getattr(s, "status", None) == "pending"]
    approved_sample = [
        s for s in samples if getattr(s, "status", None) in {"approved", "bypassed"}
    ]
    sample_uploaded = bool(samples)
    # Cups that entered print (pass 1 ledger) — progress signal, not pack eligibility.
    print_qty = physical_cup_qty_from_events(events)
    # Packable = helper-verified min across required scheduled color passes.
    required_passes = required_color_passes_from_assignments(active_assignments)
    finished_qty = eligible_verified_qty_from_events(events, required_passes)
    pack_qty = packing_qty_from_events(events)

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

        # Screen + Prepare Cup — only after valid schedule; parallel.
        if has_schedule:
            tasks.append(
                _task_row(job, "screen", "done" if screener_done else "actionable")
            )
            tasks.append(
                _task_row(job, "prepare", "done" if helper_done else "actionable")
            )

        # Downstream print chain — only after prep evidence.
        if has_schedule and screener_done and helper_done:
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
                    if pack_qty > 0:
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

        # Loading → Pengiriman (POD) — SJ-line authority; Packing is monitoring only.
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
        # Compliant POD = event with payload attachments map (Slice 1K+).
        # Legacy POD without attachments remains readable but does not mark delivery done.
        compliant_pod = False
        for e in events:
            if getattr(e, "event_type", None) != "pod":
                continue
            raw = getattr(e, "payload_json", None) or ""
            if '"attachments"' in str(raw) and "pod_photo_1" in str(raw):
                compliant_pod = True
                break
        # Loading is not gated on Packing qty (Owner rule).
        if payment_ok:
            if load_qty > 0:
                tasks.append(_task_row(job, "loading", "done"))
            else:
                tasks.append(_task_row(job, "loading", "actionable"))
            if load_qty > 0:
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
                        "delivery",
                        "blocked",
                        reason="Menunggu Loading SJ resmi",
                    )
                )

    if has_non_print:
        # Non-cetak: no fake screen/sample/print. Payment opens visibility.
        if payment_ok:
            # Use prep helper qty as stockprep evidence when non-print lines exist.
            non_print_prep = any(
                getattr(p, "role", None) == "helper"
                and Decimal(getattr(p, "qty", 0) or 0) > 0
                for p in prep_states
            )
            if non_print_prep:
                tasks.append(_task_row(job, "stockprep", "done"))
                if pack_qty > 0:
                    tasks.append(_task_row(job, "stockpack", "done"))
                else:
                    tasks.append(_task_row(job, "stockpack", "actionable"))
            else:
                # Non-print-only: design not required. Mixed: stockprep after payment.
                if has_print and not design_ok:
                    tasks.append(
                        _task_row(
                            job,
                            "stockprep",
                            "pending",
                            reason="Print gate design masih terbuka (mixed SO)",
                        )
                    )
                else:
                    tasks.append(_task_row(job, "stockprep", "actionable"))
        else:
            tasks.append(
                _task_row(
                    job,
                    "stockprep",
                    "pending",
                    reason="Menunggu payment approved/bypassed",
                )
            )

    # Unknown-only: no fake print/non-print task chain — classification lives on Jadwal/Inbox.
    # (empty list on purpose)

    for task in tasks:
        task["payment_status"] = payment_status
    return tasks


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
            }
        )

    return {
        "source": "v3_official",
        "tasks": tasks,
        "jobs": job_summaries,
        "synced_so_numbers": synced,
        "count": len(tasks),
    }
