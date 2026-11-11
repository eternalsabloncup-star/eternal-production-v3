"""Screener & helper preparation — parallel after schedule gates."""

from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.production.event import ProductionEvent
from app.models.production.job import ProductionJob
from app.models.production.prep import JobLineQty, PrepEvent, PrepState
from app.models.production.schedule import ScheduleAssignment
from app.models.user import User
from app.services.production import permissions as P
from app.services.production.engine import (
    _branch,
    _mark_terproses,
    _require,
    gates_open_for_schedule,
)


def _normalize_production_process(value: str | None) -> str:
    if value is None:
        return "unknown"
    normalized = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if normalized in {"print", "non_print", "unknown"}:
        return normalized
    return "unknown"


async def upsert_job_line_qty(
    session: AsyncSession,
    job: ProductionJob,
    *,
    so_line_id: str,
    po_qty: Decimal,
    accurate_item_id: str | None = None,
    production_process: str | None = None,
) -> JobLineQty:
    if not (so_line_id or "").strip():
        raise HTTPException(422, "Accurate line id wajib")
    if po_qty <= 0:
        raise HTTPException(422, "PO line qty harus > 0")
    process = _normalize_production_process(production_process)
    row = await session.scalar(
        select(JobLineQty).where(
            JobLineQty.job_id == job.id, JobLineQty.so_line_id == so_line_id
        )
    )
    if row is None:
        row = JobLineQty(
            job_id=job.id,
            so_line_id=so_line_id.strip(),
            po_qty=po_qty,
            accurate_item_id=(accurate_item_id or None),
            production_process=process,
        )
        session.add(row)
    else:
        if row.po_qty != po_qty:
            # Do not silently raise ceiling below already prepared helper qty.
            helper = await session.scalar(
                select(PrepState).where(
                    PrepState.job_id == job.id,
                    PrepState.so_line_id == so_line_id,
                    PrepState.role == "helper",
                )
            )
            if helper and po_qty < helper.qty:
                raise HTTPException(409, "PO qty tidak boleh di bawah qty helper siap")
            row.po_qty = po_qty
        if accurate_item_id is not None:
            row.accurate_item_id = accurate_item_id or None
        # Idempotent re-sync: keep explicit unknown; never invent print.
        row.production_process = process
    await session.flush()
    return row


async def sync_job_lines_from_so_detail(
    session: AsyncSession,
    job: ProductionJob,
    line_items: list[dict],
) -> list[JobLineQty]:
    """Upsert lines by Accurate detailItem.id. No charField heuristic mapping."""
    synced: list[JobLineQty] = []
    for line in line_items:
        if not isinstance(line, dict):
            continue
        line_id = str(
            line.get("accurate_line_id") or line.get("id") or ""
        ).strip()
        if not line_id:
            continue
        qty_raw = line.get("quantity")
        if qty_raw is None:
            qty_raw = line.get("qty")
        try:
            po_qty = Decimal(str(qty_raw))
        except Exception:
            continue
        if po_qty <= 0:
            continue
        item_id = line.get("accurate_item_id") or line.get("item_id")
        item_id_s = str(item_id).strip() if item_id is not None else None
        row = await upsert_job_line_qty(
            session,
            job,
            so_line_id=line_id,
            po_qty=po_qty,
            accurate_item_id=item_id_s or None,
            production_process=line.get("production_process"),
        )
        synced.append(row)
    return synced


async def _confirmed_pass1(session: AsyncSession, job_id: int, so_line_id: str) -> Decimal:
    produced = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job_id,
            ProductionEvent.so_line_id == so_line_id,
            ProductionEvent.event_type.in_(
                ["output_confirmed", "output_correction"]
            ),
            ProductionEvent.color_pass == 1,
        )
    )
    rejected = await session.scalar(
        select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
            ProductionEvent.job_id == job_id,
            ProductionEvent.so_line_id == so_line_id,
            ProductionEvent.event_type == "reject_verified",
            ProductionEvent.color_pass == 1,
        )
    )
    return Decimal(produced or 0) - Decimal(rejected or 0)


async def set_preparation(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    role: str,
    so_line_id: str,
    qty: Decimal,
    po_qty: Decimal | None,
    evidence_ref: str,
    idempotency_key: str,
    assignment_id: int | None = None,
    reason: str | None = None,
    as_correction: bool = False,
) -> PrepState:
    if role == "screener":
        _require(user, P.PREP_SCREENER)
    elif role == "helper":
        _require(user, P.PREP_HELPER)
    else:
        raise HTTPException(422, "Role persiapan tidak valid")
    _branch(user, job.branch_id)
    await gates_open_for_schedule(job)
    if qty < 0:
        raise HTTPException(422, "Qty persiapan tidak valid")
    if not evidence_ref.strip():
        raise HTTPException(422, "Bukti persiapan wajib")
    if assignment_id is not None:
        asg = await session.get(ScheduleAssignment, assignment_id)
        if asg is None or asg.job_id != job.id:
            raise HTTPException(404, "Assignment tidak valid untuk persiapan")

    if po_qty is not None:
        await upsert_job_line_qty(session, job, so_line_id=so_line_id, po_qty=po_qty)

    line = await session.scalar(
        select(JobLineQty).where(
            JobLineQty.job_id == job.id, JobLineQty.so_line_id == so_line_id
        )
    )
    if role == "helper":
        if line is None:
            raise HTTPException(422, "PO line qty wajib sebelum helper prepare")
        if qty > line.po_qty:
            raise HTTPException(409, "Helper qty melebihi PO line")
        confirmed = await _confirmed_pass1(session, job.id, so_line_id)
        if qty < confirmed:
            raise HTTPException(
                409, "Persiapan tidak boleh dikurangi di bawah output terkonfirmasi"
            )

    state = await session.scalar(
        select(PrepState).where(
            PrepState.job_id == job.id,
            PrepState.so_line_id == so_line_id,
            PrepState.role == role,
        )
    )
    qty_before = Decimal(state.qty) if state else Decimal("0")
    if state is None:
        state = PrepState(
            job_id=job.id,
            so_line_id=so_line_id,
            role=role,
            qty=qty,
            evidence_ref=evidence_ref.strip(),
            assignment_id=assignment_id,
            updated_by=user.id,
        )
        session.add(state)
    else:
        state.qty = qty
        state.evidence_ref = evidence_ref.strip()
        state.assignment_id = assignment_id
        state.updated_by = user.id

    event_type = "correct" if as_correction or qty_before != qty else "set"
    hist = PrepEvent(
        job_id=job.id,
        so_line_id=so_line_id,
        role=role,
        event_type=event_type,
        qty_before=qty_before,
        qty_after=qty,
        assignment_id=assignment_id,
        evidence_ref=evidence_ref.strip(),
        reason=reason,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
    )
    session.add(hist)
    # Mirror into canonical production event ledger for tracking.
    session.add(
        ProductionEvent(
            job_id=job.id,
            assignment_id=assignment_id,
            event_type=f"prep_{role}",
            so_line_id=so_line_id,
            qty_physical=qty,
            idempotency_key=f"prep-mirror:{idempotency_key}",
            actor_user_id=user.id,
            evidence_ref=evidence_ref.strip(),
            reason=reason,
            payload_json=f'{{"qty_before":"{qty_before}","qty_after":"{qty}"}}',
        )
    )
    # Changing prep invalidates sample gate if sample was required path.
    if job.sample_status == "approved":
        job.sample_status = "pending"
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Idempotency key duplikat / concurrent prep") from exc
    await _mark_terproses(session, job)
    await session.commit()
    await session.refresh(state)
    return state


async def helper_prepared_qty(
    session: AsyncSession, job_id: int, so_line_id: str
) -> Decimal:
    state = await session.scalar(
        select(PrepState).where(
            PrepState.job_id == job_id,
            PrepState.so_line_id == so_line_id,
            PrepState.role == "helper",
        )
    )
    return Decimal(state.qty) if state else Decimal("0")


async def remaining_helper_qty(
    session: AsyncSession, job_id: int, so_line_id: str
) -> Decimal:
    line = await session.scalar(
        select(JobLineQty).where(
            JobLineQty.job_id == job_id, JobLineQty.so_line_id == so_line_id
        )
    )
    prepared = await helper_prepared_qty(session, job_id, so_line_id)
    if line is None:
        return Decimal("0")
    return Decimal(line.po_qty) - prepared
