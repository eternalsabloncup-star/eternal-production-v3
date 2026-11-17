"""Phase 2 production workflow endpoints — contextual actions only."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, require_permissions
from app.db.session import get_db_session
from app.models.user import User
from app.services.production import attachments as attach_svc
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
    so_line_id: str | None = None


class DesignDecideBody(BaseModel):
    decision: str
    reason: str | None = None
    bypass: bool = False
    customer_approval: bool = False


class DesignApprovalLinkBody(BaseModel):
    so_line_id: str | None = None
    ttl_hours: int | None = None


class HelperVerifyBody(BaseModel):
    source_output_event_id: int
    qty_physical: Decimal
    idempotency_key: str = Field(min_length=8, max_length=120)
    evidence_ref: str | None = None
    reason: str | None = None


class PaymentReceiptBody(BaseModel):
    accurate_receipt_id: str
    accurate_receipt_number: str | None = None
    amount: Decimal | None = None
    note: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)


class PaymentBypassBody(BaseModel):
    reason: str
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)


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
    operator_user_id: int | None = None


class TransferBody(BaseModel):
    operator_name: str
    machine_name: str
    work_date: date
    reason: str
    operator_user_id: int | None = None


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
    accurate_sj_line_id: str
    so_line_id: str
    qty_physical: Decimal
    idempotency_key: str = Field(min_length=8, max_length=120)
    evidence_ref: str | None = None


class PodLineBody(BaseModel):
    """Actual received qty for one SJ line. Never a share of the document qty."""

    accurate_sj_line_id: str
    so_line_id: str
    qty_physical: Decimal


class PodBody(BaseModel):
    accurate_sj_id: str
    qty_physical: Decimal
    idempotency_key: str = Field(min_length=8, max_length=120)
    receiver_name: str
    # Absent: POD stays an SJ total. Present: official per-line receipt, sum must match qty_physical.
    lines: list[PodLineBody] | None = None
    # Four distinct ProductionAttachment ids — required for compliant POD.
    attachment_pod_photo_1: int
    attachment_pod_photo_2: int
    attachment_pod_sig_sender: int
    attachment_pod_sig_recipient: int
    # Optional legacy note only — never substitutes for attachments.
    evidence_ref: str | None = None


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


class CancelLoadingBody(BaseModel):
    """confirmation_cancel only (incorrect Loading record)."""

    qty_physical: Decimal
    reason: str
    idempotency_key: str = Field(min_length=8, max_length=120)
    cancel_kind: str = "confirmation_cancel"
    evidence_attachment_id: int | None = None
    evidence_ref: str | None = None


class LoadingReturnRequestBody(BaseModel):
    qty_physical: Decimal
    reason: str
    idempotency_key: str = Field(min_length=8, max_length=120)
    evidence_attachment_id: int


class LoadingReturnDecisionBody(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    reason: str | None = None


class PrepBody(BaseModel):
    so_line_id: str
    qty: Decimal
    evidence_ref: str
    idempotency_key: str = Field(min_length=8, max_length=120)
    po_qty: Decimal | None = None
    assignment_id: int | None = None
    reason: str | None = None
    as_correction: bool = False
    # Required for screener: kecil|besar. Ignored/forbidden for helper.
    screen_size: str | None = None


async def _job_summary(job, session) -> dict:
    from app.services.production.payment_gate import effective_status
    return {
        "id": job.id,
        "accurate_so_number": job.accurate_so_number,
        "accurate_id": getattr(job, "accurate_id", None),
        "branch_id": job.branch_id,
        "customer_name": getattr(job, "customer_name", None),
        "buffer_stock": getattr(job, "buffer_stock", None),
        "urgent_state": getattr(job, "urgent_state", None),
        "design_status": job.design_status,
        "payment_status": await effective_status(session, job.id),
        "sample_status": job.sample_status,
        "processing_status": job.processing_status,
        "lifecycle_status": getattr(job, "lifecycle_status", None) or "active",
        "cancelled_at": job.cancelled_at.isoformat() if getattr(job, "cancelled_at", None) else None,
        "cancel_reason": getattr(job, "cancel_reason", None),
        "cancel_gate": getattr(job, "cancel_gate", None),
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
    return await _job_summary(job, session)


@router.get("/evidence/capability")
async def evidence_capability(
    user: User = Depends(get_current_user),
):
    """Probe whether Accurate receipt/SJ verification is available."""
    from app.services.accurate_evidence import evidence_capability as cap

    _ = user
    return cap()


@router.get("/payment/receipts")
async def payment_receipts_list(
    q: str | None = None,
    payment_status: str | None = Query(None, pattern="^(approved|bypassed|pending)$"),
    receipt_status: str | None = Query(None, pattern="^(valid|invalidated|reversed)$"),
    receipts: str | None = Query(None, pattern="^(with|without)$"),
    branch: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    review_required: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    """Official per-PO payment monitor, with or without receipts (read-only, branch scoped)."""
    return await engine.list_payment_receipts(
        session,
        user,
        q=q,
        payment_status=payment_status,
        receipt_status=receipt_status,
        receipts=receipts,
        branch=branch,
        date_from=date_from,
        date_to=date_to,
        review_required=review_required,
        page=page,
        page_size=page_size,
    )


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
    return await _job_summary(job, session)


@router.get("/{job_id}/board")
async def get_job_board(
    job_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    job = await engine.get_job(session, job_id)
    return await engine.job_board(session, user, job)


@router.get("/{job_id}/loading-authority")
async def get_loading_authority(
    job_id: int,
    accurate_sj_id: str,
    accurate_sj_number: str,
    accurate_sj_line_id: str,
    so_line_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    """Narrow SJ-line Loading authority read — never invents PCS qty."""
    job = await engine.get_job(session, job_id)
    return await engine.resolve_loading_line_authority(
        session,
        user,
        job,
        accurate_sj_id=accurate_sj_id,
        accurate_sj_number=accurate_sj_number,
        accurate_sj_line_id=accurate_sj_line_id,
        so_line_id=so_line_id,
    )


class CancelJobBody(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=120)
    confirm_review: bool = False


@router.get("/{job_id}/cancel-gate")
async def cancel_gate_preview(
    job_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Preview cancel classification without mutating state."""
    from app.services.production import lifecycle as life

    from app.services.production.permissions import user_may_cancel_job

    job = await engine.get_job(session, job_id)
    if not user_may_cancel_job(user):
        from fastapi import HTTPException

        raise HTTPException(
            403,
            "Izin production.job.cancel tidak mencukupi (Direktur atau grant eksplisit)",
        )
    engine._branch(user, job.branch_id)
    return await life.classify_cancel_gate(session, job)


@router.post("/{job_id}/cancel")
async def cancel_production_job(
    job_id: int,
    body: CancelJobBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Soft-cancel ProductionJob. Never hard-deletes history or Accurate docs."""
    from app.services.production import lifecycle as life

    return await life.cancel_job(
        session,
        user,
        job_id,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
        confirm_review=body.confirm_review,
    )


@router.get("/{job_id}")
async def get_job(
    job_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    job = await engine.get_job(session, job_id)
    from app.authorization.workflow import branch_allowed
    if not branch_allowed(user, job.branch_id):
        from fastapi import HTTPException

        raise HTTPException(403, "Cabang di luar lingkup akses")
    return await _job_summary(job, session)


@router.post("/{job_id}/design/versions")
async def design_upload(
    job_id: int,
    body: DesignUploadBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    ver = await engine.upload_design(
        session,
        user,
        job,
        file_name=body.file_name,
        storage_key=body.storage_key,
        so_line_id=body.so_line_id,
    )
    return {
        "id": ver.id,
        "version_no": ver.version_no,
        "status": ver.status,
        "so_line_id": ver.so_line_id,
    }


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
        "note": (
            "Staff approve alone does not open the printed-item design gate; "
            "customer design_approval token or staff bypass required."
        ),
    }


@router.post("/{job_id}/design/versions/{version_id}/approval-links")
async def design_approval_link(
    job_id: int,
    version_id: int,
    body: DesignApprovalLinkBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    from app.services.production import customer_tokens as CT

    job = await engine.get_job(session, job_id)
    minted = await CT.mint_customer_token(
        session,
        user,
        job,
        scope=CT.SCOPE_DESIGN_APPROVAL,
        design_version_id=version_id,
        so_line_id=body.so_line_id,
        ttl_hours=body.ttl_hours,
    )
    return minted


@router.post("/{job_id}/tracking-links")
async def live_tracking_link(
    job_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    from app.services.production import customer_tokens as CT

    job = await engine.get_job(session, job_id)
    return await CT.mint_customer_token(
        session, user, job, scope=CT.SCOPE_LIVE_TRACKING
    )


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
        idempotency_key=body.idempotency_key,
    )
    return {"id": row.id, "status": row.status}


class RevalidateReceiptBody(RevokeBody):
    idempotency_key: str = Field(min_length=8, max_length=120)


@router.post("/payment/receipts/{receipt_id}/revalidate")
async def payment_receipt_revalidate(
    receipt_id: int, body: RevalidateReceiptBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await engine.revalidate_receipt(session, user, receipt_id,
        reason=body.reason, idempotency_key=body.idempotency_key)


@router.post("/{job_id}/payment/bypass")
async def payment_bypass(
    job_id: int,
    body: PaymentBypassBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    row = await engine.bypass_payment(
        session,
        user,
        job,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
    )
    return {
        "id": row.id,
        "active": row.active,
        "gate_before": getattr(row, "gate_before", None),
        "idempotency_key": getattr(row, "idempotency_key", None),
    }


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
        operator_user_id=body.operator_user_id,
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
        operator_user_id=body.operator_user_id,
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
        screen_size=body.screen_size,
    )
    remaining = await prep_svc.remaining_helper_qty(session, job.id, body.so_line_id)
    return {
        "id": state.id,
        "role": state.role,
        "prep_kind": prep_svc.PREP_KIND_BY_ROLE.get(state.role, "prepare_screen"),
        "label": "Prepare Screen",
        "qty": str(state.qty),
        "screen_size": state.screen_size,
        "helper_remaining_vs_po": str(remaining),
    }


@router.post("/{job_id}/prep/helper")
async def prep_helper(
    job_id: int,
    body: PrepBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Prepare Cup — same physical event as role=helper (no duplicate event type)."""
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
        "prep_kind": "prepare_cup",
        "label": "Prepare Cup",
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


@router.post("/{job_id}/outputs/{event_id}/helper-verifications")
async def helper_verify_output(
    job_id: int,
    event_id: int,
    body: HelperVerifyBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    if body.source_output_event_id != event_id:
        from fastapi import HTTPException

        raise HTTPException(422, "source_output_event_id harus cocok dengan path")
    event = await engine.record_helper_output_verification(
        session,
        user,
        job,
        source_output_event_id=event_id,
        qty_physical=body.qty_physical,
        idempotency_key=body.idempotency_key,
        evidence_ref=body.evidence_ref,
        reason=body.reason,
    )
    return {
        "id": event.id,
        "event_type": event.event_type,
        "qty_physical": str(event.qty_physical),
        "so_line_id": event.so_line_id,
        "color_pass": event.color_pass,
        "assignment_id": event.assignment_id,
    }


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
        accurate_sj_line_id=body.accurate_sj_line_id,
        so_line_id=body.so_line_id,
        qty_physical=body.qty_physical,
        idempotency_key=body.idempotency_key,
        evidence_ref=body.evidence_ref,
    )
    return {
        "id": event.id,
        "event_type": event.event_type,
        "accurate_sj_id": event.accurate_sj_id,
        "accurate_sj_line_id": event.accurate_sj_line_id,
        "so_line_id": event.so_line_id,
        "qty_physical": str(event.qty_physical) if event.qty_physical is not None else None,
    }


@router.post("/{job_id}/loading/{event_id}/cancel")
async def loading_cancel(
    job_id: int,
    event_id: int,
    body: CancelLoadingBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    event = await engine.cancel_loading(
        session,
        user,
        job,
        source_event_id=event_id,
        qty_physical=body.qty_physical,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
        cancel_kind=body.cancel_kind,
        evidence_attachment_id=body.evidence_attachment_id,
        evidence_ref=body.evidence_ref,
    )
    return {
        "id": event.id,
        "event_type": event.event_type,
        "accurate_sj_id": event.accurate_sj_id,
        "accurate_sj_line_id": event.accurate_sj_line_id,
        "so_line_id": event.so_line_id,
        "qty_physical": str(event.qty_physical) if event.qty_physical is not None else None,
        "payload_json": event.payload_json,
    }


@router.post("/{job_id}/loading/{event_id}/return-requests")
async def loading_return_request(
    job_id: int,
    event_id: int,
    body: LoadingReturnRequestBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    event = await engine.request_loading_return(
        session,
        user,
        job,
        source_event_id=event_id,
        qty_physical=body.qty_physical,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
        evidence_attachment_id=body.evidence_attachment_id,
    )
    return {
        "id": event.id,
        "event_type": event.event_type,
        "qty_physical": str(event.qty_physical) if event.qty_physical is not None else None,
        "payload_json": event.payload_json,
    }


@router.post("/{job_id}/loading/return-requests/{request_id}/approve")
async def loading_return_approve(
    job_id: int,
    request_id: int,
    body: LoadingReturnDecisionBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    event = await engine.approve_loading_return(
        session,
        user,
        job,
        request_event_id=request_id,
        idempotency_key=body.idempotency_key,
        reason=body.reason,
    )
    return {
        "id": event.id,
        "event_type": event.event_type,
        "qty_physical": str(event.qty_physical) if event.qty_physical is not None else None,
        "payload_json": event.payload_json,
    }


@router.post("/{job_id}/loading/return-requests/{request_id}/reject")
async def loading_return_reject(
    job_id: int,
    request_id: int,
    body: LoadingReturnDecisionBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    if not (body.reason or "").strip():
        from fastapi import HTTPException

        raise HTTPException(422, "Alasan penolakan physical return wajib")
    event = await engine.reject_loading_return(
        session,
        user,
        job,
        request_event_id=request_id,
        reason=body.reason or "",
        idempotency_key=body.idempotency_key,
    )
    return {
        "id": event.id,
        "event_type": event.event_type,
        "payload_json": event.payload_json,
    }


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
        receiver_name=body.receiver_name,
        evidence_ref=body.evidence_ref,
        lines=[line.model_dump() for line in body.lines] if body.lines else None,
        attachment_ids={
            "pod_photo_1": body.attachment_pod_photo_1,
            "pod_photo_2": body.attachment_pod_photo_2,
            "pod_sig_sender": body.attachment_pod_sig_sender,
            "pod_sig_recipient": body.attachment_pod_sig_recipient,
        },
    )
    return {
        "id": event.id,
        "event_type": event.event_type,
        "evidence_ref": event.evidence_ref,
        "payload_json": event.payload_json,
    }


@router.post("/{job_id}/attachments")
async def upload_attachment(
    job_id: int,
    accurate_sj_id: str = Form(...),
    purpose: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    job = await engine.get_job(session, job_id)
    row = await attach_svc.store_upload(
        session,
        user,
        job,
        accurate_sj_id=accurate_sj_id,
        purpose=purpose,
        upload=file,
    )
    return {
        "id": row.id,
        "purpose": row.purpose,
        "accurate_sj_id": row.accurate_sj_id,
        "content_type": row.content_type,
        "byte_size": row.byte_size,
        "content_sha256": row.content_sha256,
        "production_event_id": row.production_event_id,
    }


@router.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    row = await attach_svc.get_attachment_for_user(session, user, attachment_id)
    data = await attach_svc.read_attachment_bytes(row)
    return Response(
        content=data,
        media_type=row.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{row.purpose}-{row.id}"',
            "X-Content-SHA256": row.content_sha256,
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/{job_id}/attachments")
async def list_attachments(
    job_id: int,
    accurate_sj_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    job = await engine.get_job(session, job_id)
    from app.authorization.workflow import branch_allowed
    if not branch_allowed(user, job.branch_id):
        from fastapi import HTTPException

        raise HTTPException(403, "Cabang di luar lingkup akses")
    rows = await attach_svc.list_job_attachments(
        session, job.id, accurate_sj_id=accurate_sj_id
    )
    return {
        "items": [
            {
                "id": r.id,
                "purpose": r.purpose,
                "accurate_sj_id": r.accurate_sj_id,
                "content_type": r.content_type,
                "byte_size": r.byte_size,
                "content_sha256": r.content_sha256,
                "production_event_id": r.production_event_id,
                "uploaded_by": r.uploaded_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


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
                "assignment_id": e.assignment_id,
                "so_line_id": e.so_line_id,
                "color_pass": e.color_pass,
                "lot_code": e.lot_code,
                "actor_user_id": e.actor_user_id,
                "idempotency_key": e.idempotency_key,
                "accurate_sj_number": e.accurate_sj_number,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }
