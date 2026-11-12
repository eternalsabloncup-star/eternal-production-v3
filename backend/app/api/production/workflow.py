"""Phase 2 production workflow endpoints — contextual actions only."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, require_permissions
from app.db.session import get_db_session
from app.models.user import User
from app.services.production import engine, permissions as P
from app.services.production import prep as prep_svc

router = APIRouter(prefix="/production/jobs", tags=["production-workflow"])


class CreateJobLineBody(BaseModel):
    accurate_line_id: str | None = None
    id: str | None = None
    accurate_item_id: str | None = None
    item_id: str | None = None
    quantity: Decimal | None = None
    qty: Decimal | None = None
    production_process: str | None = None


class CreateJobBody(BaseModel):
    accurate_so_number: str
    branch_id: str
    accurate_id: str | None = None
    customer_name: str | None = None
    # Nullable — omit or null means unknown (never invent false).
    buffer_stock: bool | None = None
    urgent_state: str | None = None
    line_items: list[CreateJobLineBody] | None = None


class DesignUploadBody(BaseModel):
    file_name: str
    storage_key: str


class DesignDecideBody(BaseModel):
    decision: str
    reason: str | None = None
    bypass: bool = False
    customer_approval: bool = False


class PaymentReceiptBody(BaseModel):
    accurate_receipt_id: str
    accurate_receipt_number: str | None = None
    amount: Decimal | None = None
    note: str | None = None


class PaymentBypassBody(BaseModel):
    reason: str


class RevokeBody(BaseModel):
    reason: str


class AssignmentBody(BaseModel):
    so_line_id: str
    product_id: str | None = None
    color_pass: int = 1
    operator_name: str
    machine_name: str
    work_date: date
    qty_planned: Decimal
    location_provenance: str | None = None
    note: str | None = None


class TransferBody(BaseModel):
    operator_name: str
    machine_name: str
    work_date: date
    reason: str


class SampleUploadBody(BaseModel):
    file_name: str
    storage_key: str
    assignment_id: int | None = None


class SampleDecideBody(BaseModel):
    decision: str
    reason: str | None = None


class OutputBody(BaseModel):
    assignment_id: int
    qty_physical: Decimal
    qty_pass_ops: Decimal | None = None
    color_pass: int = 1
    idempotency_key: str = Field(min_length=8, max_length=120)
    lot_code: str | None = None
    evidence_ref: str | None = None


class RejectBody(BaseModel):
    assignment_id: int
    qty_physical: Decimal
    color_pass: int = 1
    lot_code: str | None = None
    reason: str
    idempotency_key: str = Field(min_length=8, max_length=120)


class PackingBody(BaseModel):
    so_line_id: str
    qty_physical: Decimal
    idempotency_key: str = Field(min_length=8, max_length=120)
    lot_code: str | None = None
    evidence_ref: str | None = None


class LoadingBody(BaseModel):
    accurate_sj_id: str
    accurate_sj_number: str
    qty_physical: Decimal
    idempotency_key: str = Field(min_length=8, max_length=120)
    evidence_ref: str | None = None


class PodBody(BaseModel):
    accurate_sj_id: str
    qty_physical: Decimal
    idempotency_key: str = Field(min_length=8, max_length=120)
    evidence_ref: str
    receiver_name: str


class VerifyRejectBody(BaseModel):
    approved_qty: Decimal
    reason: str | None = None


class CorrectOutputBody(BaseModel):
    source_event_id: int
    qty_physical_delta: Decimal
    reason: str
    idempotency_key: str = Field(min_length=8, max_length=120)


class CancelSjBody(BaseModel):
    accurate_sj_id: str
    reason: str
    idempotency_key: str = Field(min_length=8, max_length=120)


class PrepBody(BaseModel):
    so_line_id: str
    qty: Decimal
    evidence_ref: str
    idempotency_key: str = Field(min_length=8, max_length=120)
    po_qty: Decimal | None = None
    assignment_id: int | None = None
    reason: str | None = None
    as_correction: bool = False


def _job_summary(job) -> dict:
    return {
        "id": job.id,
        "accurate_so_number": job.accurate_so_number,
        "accurate_id": getattr(job, "accurate_id", None),
        "branch_id": job.branch_id,
        "customer_name": getattr(job, "customer_name", None),
        "buffer_stock": getattr(job, "buffer_stock", None),
        "urgent_state": getattr(job, "urgent_state", None),
        "design_status": job.design_status,
        "payment_status": job.payment_status,
        "sample_status": job.sample_status,
        "processing_status": job.processing_status,
    }


@router.post("")
async def create_job(
    body: CreateJobBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    lines_payload = None
    if body.line_items is not None:
        lines_payload = [line.model_dump() for line in body.line_items]
    job = await engine.ensure_job(
        session,
        user,
        accurate_so_number=body.accurate_so_number,
        branch_id=body.branch_id,
        accurate_id=body.accurate_id,
        customer_name=body.customer_name,
        buffer_stock=body.buffer_stock,
        urgent_state=body.urgent_state,
        line_items=lines_payload,
    )
    return _job_summary(job)


@router.get("/evidence/capability")
async def evidence_capability(
    user: User = Depends(get_current_user),
):
    """Probe whether Accurate receipt/SJ verification is available."""
    from app.services.accurate_evidence import evidence_capability as cap

    _ = user
    return cap()


class TeamTaskSyncLine(BaseModel):
    accurate_line_id: str | None = None
    id: str | None = None
    accurate_item_id: str | None = None
    item_id: str | None = None
    quantity: Decimal | None = None
    qty: Decimal | None = None
    production_process: str | None = None


class TeamTaskSyncJob(BaseModel):
    accurate_so_number: str
    branch_id: str
    accurate_id: str | None = None
    customer_name: str | None = None
    buffer_stock: bool | None = None
    urgent_state: str | None = None
    line_items: list[TeamTaskSyncLine] | None = None


class TeamTasksQueryBody(BaseModel):
    """Optional body for POST /tasks — filter + idempotent ensure_job sync."""

    so_numbers: list[str] | None = None
    sync_ensure: bool = False
    jobs: list[TeamTaskSyncJob] | None = None


@router.get("/tasks")
async def list_team_tasks(
    so: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    """Official Tugas Tim read-model from V3 jobs (no demo synthesis)."""
    so_numbers = [s.strip() for s in (so or "").split(",") if s and s.strip()] or None
    return await engine.list_team_tasks(session, user, so_numbers=so_numbers)


@router.post("/tasks")
async def list_team_tasks_with_sync(
    body: TeamTasksQueryBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Same read-model; optional idempotent ensure_job for current-page SOs."""
    payloads = None
    if body.jobs:
        payloads = []
        for job in body.jobs:
            row = job.model_dump()
            if row.get("line_items") is not None:
                row["line_items"] = [dict(x) for x in row["line_items"]]
            payloads.append(row)
    return await engine.list_team_tasks(
        session,
        user,
        so_numbers=body.so_numbers,
        sync_ensure=body.sync_ensure,
        sync_payloads=payloads,
    )


@router.get("/by-so/{so_number:path}")
async def get_job_by_so(
    so_number: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    """Read-only lookup. Returns 404 when no job exists — never creates."""
    from fastapi import HTTPException

    job = await engine.find_job_by_so(session, user, so_number)
    if job is None:
        raise HTTPException(404, "Production job belum dibuat untuk SO ini")
    return _job_summary(job)


@router.get("/{job_id}/board")
async def get_job_board(
    job_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    job = await engine.get_job(session, job_id)
    return await engine.job_board(session, user, job)


@router.get("/{job_id}")
async def get_job(
    job_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    job = await engine.get_job(session, job_id)
    if job.branch_id not in list(user.branch_ids or []):
        from fastapi import HTTPException

        raise HTTPException(403, "Cabang di luar lingkup akses")
    return _job_summary(job)


@router.post("/{job_id}/design/versions")
async def design_upload(
    job_id: int,
    body: DesignUploadBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    ver = await engine.upload_design(
        session, user, job, file_name=body.file_name, storage_key=body.storage_key
    )
    return {"id": ver.id, "version_no": ver.version_no, "status": ver.status}


@router.post("/design/versions/{version_id}/decision")
async def design_decide(
    version_id: int,
    body: DesignDecideBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    ver = await engine.decide_design(
        session,
        user,
        version_id,
        decision=body.decision,
        reason=body.reason,
        bypass=body.bypass,
        customer_approval=body.customer_approval,
    )
    return {
        "id": ver.id,
        "status": ver.status,
        "bypass": ver.bypass,
        "customer_approval": ver.customer_approval,
    }


@router.post("/{job_id}/payment/receipts")
async def payment_receipt(
    job_id: int,
    body: PaymentReceiptBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    row = await engine.record_payment_receipt(
        session,
        user,
        job,
        accurate_receipt_id=body.accurate_receipt_id,
        accurate_receipt_number=body.accurate_receipt_number,
        amount=body.amount,
        note=body.note,
    )
    return {"id": row.id, "status": row.status}


@router.post("/{job_id}/payment/bypass")
async def payment_bypass(
    job_id: int,
    body: PaymentBypassBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    row = await engine.bypass_payment(session, user, job, reason=body.reason)
    return {"id": row.id, "active": row.active}


@router.post("/payment/bypass/{bypass_id}/revoke")
async def payment_bypass_revoke(
    bypass_id: int,
    body: RevokeBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    row = await engine.revoke_payment_bypass(
        session, user, bypass_id, reason=body.reason
    )
    return {"id": row.id, "active": row.active}


@router.post("/payment/receipts/{receipt_id}/invalidate")
async def payment_receipt_invalidate(
    receipt_id: int,
    body: RevokeBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    row = await engine.invalidate_receipt(
        session, user, receipt_id, reason=body.reason
    )
    return {"id": row.id, "status": row.status}


@router.post("/{job_id}/schedule/assignments")
async def schedule_create(
    job_id: int,
    body: AssignmentBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    row = await engine.create_assignment(
        session,
        user,
        job,
        so_line_id=body.so_line_id,
        product_id=body.product_id,
        color_pass=body.color_pass,
        operator_name=body.operator_name,
        machine_name=body.machine_name,
        work_date=body.work_date,
        qty_planned=body.qty_planned,
        location_provenance=body.location_provenance,
        note=body.note,
    )
    return {"id": row.id, "status": row.status, "qty_planned": str(row.qty_planned)}


@router.post("/schedule/assignments/{assignment_id}/cancel-remaining")
async def schedule_cancel_remaining(
    assignment_id: int,
    body: RevokeBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    row = await engine.cancel_remaining(
        session, user, assignment_id, reason=body.reason
    )
    return {
        "id": row.id,
        "status": row.status,
        "qty_cancelled_remaining": str(row.qty_cancelled_remaining),
    }


@router.post("/schedule/assignments/{assignment_id}/transfer-remaining")
async def schedule_transfer(
    assignment_id: int,
    body: TransferBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    row = await engine.transfer_remaining(
        session,
        user,
        assignment_id,
        operator_name=body.operator_name,
        machine_name=body.machine_name,
        work_date=body.work_date,
        reason=body.reason,
    )
    return {"id": row.id, "status": row.status, "qty_planned": str(row.qty_planned)}


@router.post("/{job_id}/prep/screener")
async def prep_screener(
    job_id: int,
    body: PrepBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    state = await prep_svc.set_preparation(
        session,
        user,
        job,
        role="screener",
        so_line_id=body.so_line_id,
        qty=body.qty,
        po_qty=body.po_qty,
        evidence_ref=body.evidence_ref,
        idempotency_key=body.idempotency_key,
        assignment_id=body.assignment_id,
        reason=body.reason,
        as_correction=body.as_correction,
    )
    remaining = await prep_svc.remaining_helper_qty(session, job.id, body.so_line_id)
    return {
        "id": state.id,
        "role": state.role,
        "qty": str(state.qty),
        "helper_remaining_vs_po": str(remaining),
    }


@router.post("/{job_id}/prep/helper")
async def prep_helper(
    job_id: int,
    body: PrepBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    state = await prep_svc.set_preparation(
        session,
        user,
        job,
        role="helper",
        so_line_id=body.so_line_id,
        qty=body.qty,
        po_qty=body.po_qty,
        evidence_ref=body.evidence_ref,
        idempotency_key=body.idempotency_key,
        assignment_id=body.assignment_id,
        reason=body.reason,
        as_correction=body.as_correction,
    )
    remaining = await prep_svc.remaining_helper_qty(session, job.id, body.so_line_id)
    return {
        "id": state.id,
        "role": state.role,
        "qty": str(state.qty),
        "remaining_vs_po": str(remaining),
    }


@router.post("/{job_id}/samples")
async def sample_upload(
    job_id: int,
    body: SampleUploadBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    ver = await engine.upload_sample(
        session,
        user,
        job,
        file_name=body.file_name,
        storage_key=body.storage_key,
        assignment_id=body.assignment_id,
    )
    return {"id": ver.id, "version_no": ver.version_no, "status": ver.status}


@router.post("/samples/{sample_id}/decision")
async def sample_decide(
    sample_id: int,
    body: SampleDecideBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    ver = await engine.decide_sample(
        session, user, sample_id, decision=body.decision, reason=body.reason
    )
    return {"id": ver.id, "status": ver.status}


@router.post("/{job_id}/outputs")
async def output_confirm(
    job_id: int,
    body: OutputBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    event = await engine.confirm_output(
        session,
        user,
        job,
        assignment_id=body.assignment_id,
        qty_physical=body.qty_physical,
        qty_pass_ops=body.qty_pass_ops,
        color_pass=body.color_pass,
        idempotency_key=body.idempotency_key,
        lot_code=body.lot_code,
        evidence_ref=body.evidence_ref,
    )
    return {"id": event.id, "event_type": event.event_type}


@router.post("/{job_id}/rejects")
async def reject_record(
    job_id: int,
    body: RejectBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    event = await engine.record_reject(
        session,
        user,
        job,
        assignment_id=body.assignment_id,
        qty_physical=body.qty_physical,
        color_pass=body.color_pass,
        lot_code=body.lot_code,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
    )
    return {"id": event.id, "event_type": event.event_type}


@router.post("/rejects/{event_id}/verify")
async def reject_verify(
    event_id: int,
    body: VerifyRejectBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    event = await engine.verify_reject(
        session,
        user,
        event_id,
        approved_qty=body.approved_qty,
        reason=body.reason,
    )
    return {"id": event.id, "event_type": event.event_type}


@router.post("/{job_id}/outputs/corrections")
async def output_correct(
    job_id: int,
    body: CorrectOutputBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    event = await engine.correct_output(
        session,
        user,
        job,
        source_event_id=body.source_event_id,
        qty_physical_delta=body.qty_physical_delta,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
    )
    return {"id": event.id, "event_type": event.event_type}


@router.post("/{job_id}/packing")
async def packing_record(
    job_id: int,
    body: PackingBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    event = await engine.record_packing(
        session,
        user,
        job,
        so_line_id=body.so_line_id,
        lot_code=body.lot_code,
        qty_physical=body.qty_physical,
        idempotency_key=body.idempotency_key,
        evidence_ref=body.evidence_ref,
    )
    return {"id": event.id, "event_type": event.event_type}


@router.post("/{job_id}/loading")
async def loading_record(
    job_id: int,
    body: LoadingBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    event = await engine.record_loading(
        session,
        user,
        job,
        accurate_sj_id=body.accurate_sj_id,
        accurate_sj_number=body.accurate_sj_number,
        qty_physical=body.qty_physical,
        idempotency_key=body.idempotency_key,
        evidence_ref=body.evidence_ref,
    )
    return {"id": event.id, "event_type": event.event_type}


@router.post("/{job_id}/pod")
async def pod_record(
    job_id: int,
    body: PodBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    event = await engine.record_pod(
        session,
        user,
        job,
        accurate_sj_id=body.accurate_sj_id,
        qty_physical=body.qty_physical,
        idempotency_key=body.idempotency_key,
        evidence_ref=body.evidence_ref,
        receiver_name=body.receiver_name,
    )
    return {"id": event.id, "event_type": event.event_type}


@router.post("/{job_id}/sj/cancel")
async def sj_cancel(
    job_id: int,
    body: CancelSjBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    event = await engine.cancel_sj(
        session,
        user,
        job,
        accurate_sj_id=body.accurate_sj_id,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
    )
    return {"id": event.id, "event_type": event.event_type}


@router.get("/{job_id}/tracking")
async def tracking(
    job_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    events = await engine.tracking_timeline(session, user, job)
    return {
        "job_id": job.id,
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "qty_physical": str(e.qty_physical) if e.qty_physical is not None else None,
                "qty_pass_ops": str(e.qty_pass_ops) if e.qty_pass_ops is not None else None,
                "accurate_sj_number": e.accurate_sj_number,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }
