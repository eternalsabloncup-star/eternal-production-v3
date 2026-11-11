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


async def ensure_job(
    session: AsyncSession,
    user: User,
    *,
    accurate_so_number: str,
    branch_id: str,
    accurate_id: str | None = None,
    customer_name: str | None = None,
) -> ProductionJob:
    _require(user, P.JOB_CREATE)
    _branch(user, branch_id)
    existing = await session.scalar(
        select(ProductionJob).where(
            ProductionJob.accurate_so_number == accurate_so_number
        )
    )
    if existing:
        _branch(user, existing.branch_id)
        return existing
    job = ProductionJob(
        accurate_so_number=accurate_so_number,
        accurate_id=accurate_id,
        branch_id=branch_id,
        customer_name=customer_name,
        processing_status="Baru",
    )
    session.add(job)
    await session.flush()
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


async def gates_open_for_schedule(job: ProductionJob) -> None:
    if job.design_status not in {"approved", "bypassed"}:
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
    row = PaymentReceiptRef(
        job_id=job.id,
        accurate_receipt_id=accurate_receipt_id.strip(),
        accurate_receipt_number=accurate_receipt_number,
        amount=amount,
        status="valid",
        recorded_by=user.id,
        note=note,
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
    await gates_open_for_schedule(job)
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
    produced = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type.in_(
                ["output_confirmed", "output_correction"]
            ),
            ProductionEvent.so_line_id == so_line_id,
        )
    )
    # Only authorized verified rejects reduce packable physical qty.
    rejected = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "reject_verified",
            ProductionEvent.so_line_id == so_line_id,
        )
    )
    packed = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "packing_batch",
            ProductionEvent.so_line_id == so_line_id,
        )
    )
    available = Decimal(produced or 0) - Decimal(rejected or 0) - Decimal(packed or 0)
    if qty_physical > available:
        raise HTTPException(409, "Overpacking: melebihi qty fisik tersedia")
    event = ProductionEvent(
        job_id=job.id,
        event_type="packing_batch",
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
    packed = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "packing_batch",
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
    loaded = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "loading",
            ProductionEvent.accurate_sj_id == accurate_sj_id,
        )
    )
    if Decimal(loaded or 0) <= 0:
        raise HTTPException(409, "POD tidak boleh bypass Loading")
    if qty_physical <= 0 or qty_physical > Decimal(loaded or 0):
        raise HTTPException(409, "Qty POD tidak valid terhadap Loading")
    event = ProductionEvent(
        job_id=job.id,
        event_type="pod",
        qty_physical=qty_physical,
        accurate_sj_id=accurate_sj_id,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
        evidence_ref=evidence_ref,
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
