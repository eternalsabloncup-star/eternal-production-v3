"""Single canonical workflow engine for Production V3."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
REJECT_EVENT_TYPES = frozenset({"reject_verified"})
# Color pass 1 records cups entering print; later passes are work-ops on the same cups.
# Packing eligibility requires ALL scheduled required passes (min across passes), not pass 1 alone.
PHYSICAL_CUP_COLOR_PASS = 1
_CANCELLED_ASSIGNMENT = frozenset({"cancelled", "canceled", "void", "cancelled_remaining"})


def _require(user: User, *perms: str) -> None:
    have = set(user.permissions or [])
    if not set(perms).issubset(have):
        raise HTTPException(403, "Izin tidak mencukupi")


def _branch(user: User, branch_id: str) -> None:
    if branch_id not in list(user.branch_ids or []):
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
    """Physical cups finished through ALL required color passes — never sum passes.

    Eligible = min(net qty per required pass). Pass 1 alone is never finished proof
    when a higher pass is scheduled for the line.
    """
    passes = frozenset(int(p) for p in required_passes) or frozenset(
        {PHYSICAL_CUP_COLOR_PASS}
    )
    return min(
        qty_for_color_pass_from_events(events, p, so_line_id=so_line_id) for p in passes
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
) -> ProductionJob:
    """Create or refresh job. Classifications stay null/unknown unless explicit."""
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
    if needs_design and job.design_status not in {"approved", "bypassed"}:
        raise HTTPException(409, "Design belum disetujui/bypass")
    if job.payment_status not in {"approved", "bypassed"}:
        raise HTTPException(409, "Payment belum disetujui/bypass")


# ---- Design ----


async def upload_design(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    file_name: str,
    storage_key: str,
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
            job.design_status = "pending"
        elif row.status == "pending":
            row.status = "superseded"
    ver = DesignVersion(
        job_id=job.id,
        version_no=int(max_v or 0) + 1,
        file_name=file_name,
        storage_key=storage_key,
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
    ver.status = decision if not bypass else "approved"
    ver.bypass = bypass
    ver.customer_approval = customer_approval
    ver.decision_by = user.id
    ver.decision_reason = reason
    ver.decided_at = datetime.now(UTC)
    if decision == "rejected" and not bypass:
        job.design_status = "rejected"
    else:
        job.design_status = "bypassed" if bypass else "approved"
    await session.commit()
    await session.refresh(ver)
    return ver


# ---- Payment ----


async def record_payment_receipt(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    accurate_receipt_id: str,
    accurate_receipt_number: str | None = None,
    amount: Decimal | None = None,
    note: str | None = None,
) -> PaymentReceiptRef:
    _require(user, P.PAYMENT_RECORD)
    _branch(user, job.branch_id)
    if not accurate_receipt_id.strip():
        raise HTTPException(422, "Referensi receipt Accurate wajib")
    from app.services.accurate_evidence import require_valid_receipt

    evidence = await require_valid_receipt(
        accurate_receipt_id,
        expected_so_number=job.accurate_so_number,
        expected_branch_id=job.branch_id,
    )
    row = PaymentReceiptRef(
        job_id=job.id,
        accurate_receipt_id=accurate_receipt_id.strip(),
        accurate_receipt_number=accurate_receipt_number,
        amount=amount,
        status="valid",
        recorded_by=user.id,
        note=(note or "")
        + (
            f" | evidence:{evidence.get('mode')}:{evidence.get('payload_status', '')}"
        ),
    )
    session.add(row)
    # Valid receipt opens payment gate (no manual approve without evidence).
    job.payment_status = "approved"
    await _mark_terproses(session, job)
    await session.commit()
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
    _branch(user, job.branch_id)
    if not reason.strip():
        raise HTTPException(422, "Bypass payment memerlukan alasan")
    row = PaymentBypass(
        job_id=job.id,
        reason=reason.strip(),
        authorized_by=user.id,
        active=True,
    )
    session.add(row)
    job.payment_status = "bypassed"
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
    row = await session.get(PaymentBypass, bypass_id)
    if row is None or not row.active:
        raise HTTPException(404, "Bypass tidak aktif")
    job = await get_job(session, row.job_id)
    _branch(user, job.branch_id)
    row.active = False
    row.revoked_by = user.id
    row.revoke_reason = reason
    row.revoked_at = datetime.now(UTC)
    # Re-evaluate gate: any valid receipt keeps approval; else pending.
    valid = await session.scalar(
        select(func.count())
        .select_from(PaymentReceiptRef)
        .where(
            PaymentReceiptRef.job_id == job.id,
            PaymentReceiptRef.status == "valid",
        )
    )
    job.payment_status = "approved" if int(valid or 0) > 0 else "pending"
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
    row = await session.get(PaymentReceiptRef, receipt_id)
    if row is None:
        raise HTTPException(404, "Receipt tidak ditemukan")
    job = await get_job(session, row.job_id)
    _branch(user, job.branch_id)
    row.status = "invalidated"
    row.note = (row.note or "") + f" | invalidated: {reason}"
    # Close gate for unfinished work if no other valid evidence/bypass.
    valid = await session.scalar(
        select(func.count())
        .select_from(PaymentReceiptRef)
        .where(
            PaymentReceiptRef.job_id == job.id,
            PaymentReceiptRef.status == "valid",
            PaymentReceiptRef.id != row.id,
        )
    )
    active_bypass = await session.scalar(
        select(func.count())
        .select_from(PaymentBypass)
        .where(PaymentBypass.job_id == job.id, PaymentBypass.active.is_(True))
    )
    if int(valid or 0) == 0 and int(active_bypass or 0) == 0:
        job.payment_status = "pending"
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
    _branch(user, job.branch_id)
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
        payload_json=f'{{"source_output_id":{src.id}}}',
    )
    session.add(event)
    if src.assignment_id:
        assignment = await session.get(ScheduleAssignment, src.assignment_id)
        if assignment:
            assignment.qty_confirmed = assignment.qty_confirmed + qty_physical_delta
            if assignment.qty_confirmed < 0:
                raise HTTPException(409, "Koreksi membuat qty confirmed negatif")
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Idempotency key duplikat") from exc
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
    """Preserve cancelled/superseded SJ identity as history event."""
    _require(user, P.DELIVERY_MANAGE)
    _branch(user, job.branch_id)
    if not accurate_sj_id.strip() or not reason.strip():
        raise HTTPException(422, "Pembatalan SJ memerlukan identitas dan alasan")
    loaded = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "loading",
            ProductionEvent.accurate_sj_id == accurate_sj_id,
        )
    )
    event = ProductionEvent(
        job_id=job.id,
        event_type="sj_cancelled",
        qty_physical=Decimal(loaded or 0),
        accurate_sj_id=accurate_sj_id.strip(),
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
    # Eligible finished = min(net qty per required pass). Never pass-1-only when
    # a higher pass is scheduled; never sum multi-color work into packable stock.
    pass_nets: list[Decimal] = []
    for pass_no in sorted(required):
        produced = await session.scalar(
            select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
                ProductionEvent.job_id == job.id,
                ProductionEvent.event_type.in_(list(OUTPUT_EVENT_TYPES)),
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
        pass_nets.append(Decimal(produced or 0) - Decimal(rejected or 0))
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
            "Overpacking: melebihi qty fisik selesai semua warna "
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


async def record_loading(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    accurate_sj_id: str,
    accurate_sj_number: str,
    qty_physical: Decimal,
    idempotency_key: str,
    evidence_ref: str | None = None,
) -> ProductionEvent:
    _require(user, P.DELIVERY_MANAGE)
    _branch(user, job.branch_id)
    if not accurate_sj_id.strip() or not accurate_sj_number.strip():
        raise HTTPException(422, "Identitas SJ Accurate wajib")
    if qty_physical <= 0:
        raise HTTPException(422, "Qty loading harus > 0")
    from app.services.accurate_evidence import require_valid_sj

    await require_valid_sj(
        accurate_sj_id=accurate_sj_id,
        accurate_sj_number=accurate_sj_number,
        expected_so_number=job.accurate_so_number,
        expected_branch_id=job.branch_id,
    )
    packed = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type.in_(list(PACKING_EVENT_TYPES)),
        )
    )
    loaded = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "loading",
        )
    )
    cancelled = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "sj_cancelled",
        )
    )
    available = (
        Decimal(packed or 0) - Decimal(loaded or 0) + Decimal(cancelled or 0)
    )
    if qty_physical > available:
        raise HTTPException(409, "Loading melebihi qty packing tersedia")
    event = ProductionEvent(
        job_id=job.id,
        event_type="loading",
        qty_physical=qty_physical,
        accurate_sj_id=accurate_sj_id.strip(),
        accurate_sj_number=accurate_sj_number.strip(),
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


async def record_pod(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    accurate_sj_id: str,
    qty_physical: Decimal,
    idempotency_key: str,
    evidence_ref: str,
    receiver_name: str,
) -> ProductionEvent:
    _require(user, P.DELIVERY_MANAGE)
    _branch(user, job.branch_id)
    if not evidence_ref.strip() or not receiver_name.strip():
        raise HTTPException(422, "POD memerlukan bukti dan identitas penerima")
    cancelled = await session.scalar(
        select(func.count())
        .select_from(ProductionEvent)
        .where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "sj_cancelled",
            ProductionEvent.accurate_sj_id == accurate_sj_id,
        )
    )
    if int(cancelled or 0) > 0:
        raise HTTPException(409, "SJ sudah dibatalkan; gunakan SJ aktif")
    # Re-verify SJ at POD time — never rely solely on prior loading snapshot.
    loading_row = await session.scalar(
        select(ProductionEvent)
        .where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "loading",
            ProductionEvent.accurate_sj_id == accurate_sj_id.strip(),
        )
        .order_by(ProductionEvent.id.desc())
        .limit(1)
    )
    if loading_row is not None and (loading_row.accurate_sj_number or "").strip():
        from app.services.accurate_evidence import require_valid_sj

        await require_valid_sj(
            accurate_sj_id=accurate_sj_id,
            accurate_sj_number=loading_row.accurate_sj_number,
            expected_so_number=job.accurate_so_number,
            expected_branch_id=job.branch_id,
        )
    loaded = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "loading",
            ProductionEvent.accurate_sj_id == accurate_sj_id,
        )
    )
    already_pod = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "pod",
            ProductionEvent.accurate_sj_id == accurate_sj_id,
        )
    )
    remaining = Decimal(loaded or 0) - Decimal(already_pod or 0)
    if Decimal(loaded or 0) <= 0:
        raise HTTPException(409, "POD tidak boleh bypass Loading")
    if qty_physical <= 0 or qty_physical > remaining:
        raise HTTPException(409, "Qty POD tidak valid terhadap sisa Loading SJ")
    # V1 requires 2 photos + sender/recipient signatures. Current schema has a single
    # evidence_ref string — full multi-attachment POD is BLOCKED without migration.
    # Fail closed on empty evidence; do not invent multi-proof from one generic ref.
    event = ProductionEvent(
        job_id=job.id,
        event_type="pod",
        qty_physical=qty_physical,
        accurate_sj_id=accurate_sj_id,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
        evidence_ref=evidence_ref.strip(),
        reason=f"receiver:{receiver_name.strip()}",
    )
    session.add(event)
    try:
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


async def job_board(session: AsyncSession, user: User, job: ProductionJob) -> dict:
    """Authoritative drawer payload for one selected SO/job."""
    _require(user, P.JOB_READ)
    _branch(user, job.branch_id)
    from app.models.production.prep import JobLineQty, PrepEvent, PrepState

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
    return {
        "job": {
            "id": job.id,
            "accurate_so_number": job.accurate_so_number,
            "accurate_id": job.accurate_id,
            "branch_id": job.branch_id,
            "customer_name": job.customer_name,
            "buffer_stock": job.buffer_stock,
            "urgent_state": job.urgent_state,
            "design_status": job.design_status,
            "payment_status": job.payment_status,
            "sample_status": job.sample_status,
            "processing_status": job.processing_status,
        },
        "design_versions": [
            {
                "id": d.id,
                "version_no": d.version_no,
                "file_name": d.file_name,
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
                "reason": e.reason,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


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
    payment_ok = job.payment_status in {"approved", "bypassed"}
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
    # Packable finished cups = min across required scheduled color passes.
    required_passes = required_color_passes_from_assignments(active_assignments)
    finished_qty = eligible_finished_qty_from_events(events, required_passes)
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
        for payload in sync_payloads:
            so = str(payload.get("accurate_so_number") or "").strip()
            branch_id = str(payload.get("branch_id") or "").strip()
            if not so or not branch_id:
                continue
            if branch_id not in list(user.branch_ids or []):
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
            )
            synced.append(so)

    from app.models.production.prep import JobLineQty, PrepState

    q = select(ProductionJob)
    if so_numbers:
        cleaned = [s.strip() for s in so_numbers if s and str(s).strip()]
        if cleaned:
            q = q.where(ProductionJob.accurate_so_number.in_(cleaned))
    jobs = (await session.scalars(q.order_by(ProductionJob.id.asc()))).all()
    allowed_branches = set(user.branch_ids or [])
    jobs = [j for j in jobs if j.branch_id in allowed_branches]

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
        )
        tasks.extend(derived)
        job_summaries.append(
            {
                "id": job.id,
                "accurate_so_number": job.accurate_so_number,
                "branch_id": job.branch_id,
                "customer_name": job.customer_name,
                "design_status": job.design_status,
                "payment_status": job.payment_status,
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
