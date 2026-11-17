"""Screener & helper preparation — parallel after schedule gates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.production.event import ProductionEvent
from app.models.production.job import ProductionJob
from app.models.production.prep import (
    LINE_STATUS_ACTIVE,
    LINE_STATUS_CONFLICT,
    LINE_STATUS_REMOVED,
    JobLineQty,
    PrepEvent,
    PrepState,
)
from app.models.production.schedule import ScheduleAssignment
from app.models.user import User
from app.services.production import permissions as P
from app.services.production.engine import (
    _branch,
    _mark_terproses,
    _require,
    gates_open_for_schedule,
)
from app.services.production.lifecycle import require_job_active

SCREEN_SIZES = frozenset({"kecil", "besar"})
# Contract: role=helper on a print line IS Prepare Cup (no parallel physical event type).
PREP_ROLE_SCREEN = "screener"
PREP_ROLE_CUP = "helper"
PREP_KIND_BY_ROLE = {
    PREP_ROLE_SCREEN: "prepare_screen",
    PREP_ROLE_CUP: "prepare_cup",
}


def _normalize_production_process(value: str | None) -> str:
    if value is None:
        return "unknown"
    normalized = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if normalized in {"print", "non_print", "unknown"}:
        return normalized
    return "unknown"


async def _line_has_committed_work(
    session: AsyncSession, job_id: int, so_line_id: str
) -> bool:
    for stmt in (
        select(func.count())
        .select_from(ScheduleAssignment)
        .where(
            ScheduleAssignment.job_id == job_id,
            ScheduleAssignment.so_line_id == so_line_id,
        ),
        select(func.count())
        .select_from(ProductionEvent)
        .where(
            ProductionEvent.job_id == job_id,
            ProductionEvent.so_line_id == so_line_id,
        ),
        select(func.count())
        .select_from(PrepState)
        .where(PrepState.job_id == job_id, PrepState.so_line_id == so_line_id),
    ):
        if int(await session.scalar(stmt) or 0) > 0:
            return True
    return False


async def upsert_job_line_qty(
    session: AsyncSession,
    job: ProductionJob,
    *,
    so_line_id: str,
    po_qty: Decimal,
    accurate_item_id: str | None = None,
    production_process: str | None = None,
    from_accurate: bool = False,
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
            line_status=LINE_STATUS_ACTIVE,
        )
        session.add(row)
    else:
        # Reappearing source line clears removed marker when qty/process reconcile.
        if row.line_status == LINE_STATUS_REMOVED:
            row.line_status = LINE_STATUS_ACTIVE
            row.removed_from_source_at = None
            row.revision_note = None
        if from_accurate and production_process is not None:
            prev = (row.production_process or "unknown").strip().lower()
            if prev != process and await _line_has_committed_work(
                session, job.id, so_line_id
            ):
                row.line_status = LINE_STATUS_CONFLICT
                row.revision_note = (
                    f"Klasifikasi berubah {prev} → {process} sementara line sudah beraktivitas"
                )
                # Do not silently rewrite classification once work exists.
                if accurate_item_id is not None:
                    row.accurate_item_id = accurate_item_id or None
                await session.flush()
                return row
        if from_accurate and row.po_qty != po_qty:
            committed = await _line_has_committed_work(session, job.id, so_line_id)
            if committed:
                completed = await _confirmed_pass1(session, job.id, so_line_id)
                # Historical approvals and quantities stay; change is surfaced for review.
                row.source_qty = po_qty
                row.drift_detected_at = func.now()
                if po_qty < completed:
                    row.line_status = LINE_STATUS_CONFLICT
                    row.revision_note = (
                        f"Qty Accurate {po_qty} < qty completed {completed}"
                    )
                elif row.line_status != LINE_STATUS_CONFLICT:
                    row.line_status = LINE_STATUS_ACTIVE
                    row.revision_note = "Qty Accurate berubah setelah aktivitas — butuh review"
                if accurate_item_id is not None:
                    row.accurate_item_id = accurate_item_id or None
                await session.flush()
                return row
        if from_accurate and row.po_qty == po_qty and row.source_qty is not None:
            row.source_qty = None
            row.drift_detected_at = None
            if row.line_status == LINE_STATUS_CONFLICT and not (
                row.revision_note or ""
            ).startswith("Klasifikasi"):
                row.line_status = LINE_STATUS_ACTIVE
                row.revision_note = None
        if row.po_qty != po_qty:
            if from_accurate:
                row.source_qty = None
                row.drift_detected_at = None
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
        # Only overwrite process when caller supplies an explicit value.
        # Helper/screener qty updates must not clobber Accurate classification.
        if production_process is not None:
            row.production_process = process
        if from_accurate and row.line_status != LINE_STATUS_CONFLICT:
            row.line_status = LINE_STATUS_ACTIVE
            row.removed_from_source_at = None
    await session.flush()
    return row


async def sync_job_lines_from_so_detail(
    session: AsyncSession,
    job: ProductionJob,
    line_items: list[dict],
) -> list[JobLineQty]:
    """Upsert lines by Accurate detailItem.id. No charField heuristic mapping.

    Slice 1M: unverified / missing / non-finite quantity must not become a
    production line with verified zero — eligibility rejects those rows.
    Fase 1C: lines missing from Accurate are marked removed/conflict — never
    hard-deleted. Does not fake a successful silent sync.
    """
    require_job_active(job)
    synced: list[JobLineQty] = []
    seen_ids: set[str] = set()
    for line in line_items:
        if not isinstance(line, dict):
            continue
        line_id = str(
            line.get("accurate_line_id") or line.get("id") or ""
        ).strip()
        if not line_id:
            continue
        qty_verified = line.get("qty_verified")
        qty_raw = line.get("quantity")
        if qty_raw is None:
            qty_raw = line.get("qty")
        if qty_verified is False or qty_raw is None:
            raise HTTPException(
                422,
                "Qty line Accurate belum terverifikasi — tidak dapat dijadwalkan/diproses",
            )
        try:
            po_qty = Decimal(str(qty_raw))
        except Exception as exc:
            raise HTTPException(
                422,
                "Qty line Accurate tidak valid — tidak dapat dijadwalkan/diproses",
            ) from exc
        if not po_qty.is_finite():
            raise HTTPException(
                422,
                "Qty line Accurate tidak valid — tidak dapat dijadwalkan/diproses",
            )
        if po_qty <= 0:
            # Official zero: no production line to schedule; do not invent work.
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
            from_accurate=True,
        )
        seen_ids.add(line_id)
        synced.append(row)

    existing_rows = (
        await session.scalars(select(JobLineQty).where(JobLineQty.job_id == job.id))
    ).all()
    now = datetime.now(UTC)
    for row in existing_rows:
        if row.so_line_id in seen_ids:
            continue
        if await _line_has_committed_work(session, job.id, row.so_line_id):
            row.line_status = LINE_STATUS_CONFLICT
            row.revision_note = (
                "Line hilang dari Accurate sementara sudah ada assignment/progress"
            )
        else:
            row.line_status = LINE_STATUS_REMOVED
            row.removed_from_source_at = now
            row.revision_note = "Line dihapus dari sumber Accurate"
    await session.flush()
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
    screen_size: str | None = None,
) -> PrepState:
    if role == "screener":
        _require(user, P.PREP_SCREENER)
    elif role == "helper":
        _require(user, P.PREP_HELPER)
    else:
        raise HTTPException(422, "Role persiapan tidak valid")
    _branch(user, job.branch_id)
    existing_line = await session.scalar(
        select(JobLineQty).where(
            JobLineQty.job_id == job.id, JobLineQty.so_line_id == so_line_id
        )
    )
    # Classification is canonical (Accurate sync / explicit JobLineQty). Never invent PRINT.
    if existing_line is None:
        raise HTTPException(
            409,
            "Klasifikasi line belum tersedia (JobLineQty hilang). "
            "Sinkronkan line dari sumber canonical sebelum Prepare Screen/Cup.",
        )
    proc_existing = _normalize_production_process(existing_line.production_process)
    if proc_existing == "non_print":
        raise HTTPException(
            409,
            "Line non-print tidak mendapat Prepare Screen/Cup. Packing langsung setelah payment dan bukti fisik.",
        )
    if proc_existing != "print":
        raise HTTPException(
            409,
            "Klasifikasi line masih UNKNOWN — Prepare Screen/Cup ditolak sampai "
            "production_process=print dari sumber canonical (bukan dari aksi prep).",
        )
    await gates_open_for_schedule(job, session)
    if qty < 0:
        raise HTTPException(422, "Qty persiapan tidak valid")
    if not evidence_ref.strip():
        raise HTTPException(422, "Bukti persiapan wajib")
    size_n: str | None = None
    if role == "screener":
        # Canonical owner of screen size is PrepState/PrepEvent (screener work).
        raw = (screen_size or "").strip().lower()
        if raw not in SCREEN_SIZES:
            raise HTTPException(422, "screen_size wajib: kecil|besar")
        size_n = raw
    elif screen_size is not None and str(screen_size).strip():
        raise HTTPException(422, "screen_size hanya untuk role screener")
    # Screener/Helper only after at least one active schedule assignment on the line.
    scheduled = await session.scalar(
        select(func.count())
        .select_from(ScheduleAssignment)
        .where(
            ScheduleAssignment.job_id == job.id,
            ScheduleAssignment.so_line_id == so_line_id,
            ScheduleAssignment.status.in_(["active", "completed"]),
        )
    )
    if int(scheduled or 0) <= 0:
        raise HTTPException(409, "Persiapan hanya setelah penjadwalan valid pada line")
    if assignment_id is not None:
        asg = await session.get(ScheduleAssignment, assignment_id)
        if asg is None or asg.job_id != job.id:
            raise HTTPException(404, "Assignment tidak valid untuk persiapan")

    # Qty ceiling update only — never rewrite production_process from prep payload.
    if po_qty is not None:
        await upsert_job_line_qty(session, job, so_line_id=so_line_id, po_qty=po_qty)

    line = await session.scalar(
        select(JobLineQty).where(
            JobLineQty.job_id == job.id, JobLineQty.so_line_id == so_line_id
        )
    )
    if line is None or _normalize_production_process(line.production_process) != "print":
        raise HTTPException(
            409,
            "Prepare Screen/Cup hanya untuk line cetak terklasifikasi (production_process=print).",
        )
    if role == PREP_ROLE_CUP:
        if qty > line.po_qty:
            raise HTTPException(409, "Prepare Cup qty melebihi PO line")
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
            screen_size=size_n,
            assignment_id=assignment_id,
            updated_by=user.id,
        )
        session.add(state)
    else:
        state.qty = qty
        state.evidence_ref = evidence_ref.strip()
        state.assignment_id = assignment_id
        state.updated_by = user.id
        if role == "screener":
            # Size correction updates current state; history keeps prior values.
            state.screen_size = size_n

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
        screen_size=size_n,
        reason=reason,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
    )
    session.add(hist)
    # Mirror into canonical production event ledger for tracking.
    payload = {"qty_before": str(qty_before), "qty_after": str(qty)}
    if size_n:
        payload["screen_size"] = size_n
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
            payload_json=json.dumps(payload, separators=(",", ":")),
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
            PrepState.role == PREP_ROLE_CUP,
        )
    )
    return Decimal(state.qty) if state else Decimal("0")


async def screener_prepared_qty(
    session: AsyncSession, job_id: int, so_line_id: str
) -> Decimal:
    state = await session.scalar(
        select(PrepState).where(
            PrepState.job_id == job_id,
            PrepState.so_line_id == so_line_id,
            PrepState.role == PREP_ROLE_SCREEN,
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


async def require_print_preps_ready_for_sample(
    session: AsyncSession,
    job: ProductionJob,
    *,
    so_line_id: str | None = None,
) -> None:
    """Sample upload/approve only after Prepare Screen AND Prepare Cup READY per print line.

    Parallel: screen and cup do not wait on each other; both must be READY before sample.
    Multi-line: one READY line never authorizes another PENDING line.
    UNKNOWN / missing classification never counts as print and never opens the gate.
    """
    line_map = {
        str(ln.so_line_id): ln
        for ln in (
            await session.scalars(select(JobLineQty).where(JobLineQty.job_id == job.id))
        ).all()
        if str(getattr(ln, "so_line_id", "") or "").strip()
    }

    if so_line_id:
        candidate_ids = [str(so_line_id).strip()]
    else:
        scheduled = (
            await session.scalars(
                select(ScheduleAssignment.so_line_id).where(
                    ScheduleAssignment.job_id == job.id,
                    ScheduleAssignment.status.in_(["active", "completed"]),
                )
            )
        ).all()
        candidate_ids = sorted(
            {
                str(lid).strip()
                for lid in scheduled
                if str(lid or "").strip()
            }
        )
        if not candidate_ids:
            candidate_ids = [
                lid
                for lid, ln in line_map.items()
                if str(getattr(ln, "line_status", LINE_STATUS_ACTIVE) or LINE_STATUS_ACTIVE)
                == LINE_STATUS_ACTIVE
                and _normalize_production_process(getattr(ln, "production_process", None))
                == "print"
            ]

    unresolved: list[str] = []
    pending_prep: list[str] = []
    checked_print = 0
    for lid in candidate_ids:
        ln = line_map.get(lid)
        if ln is None:
            unresolved.append(lid)
            continue
        status = str(getattr(ln, "line_status", LINE_STATUS_ACTIVE) or LINE_STATUS_ACTIVE)
        if status != LINE_STATUS_ACTIVE:
            continue
        proc = _normalize_production_process(getattr(ln, "production_process", None))
        if proc == "non_print":
            continue
        if proc != "print":
            unresolved.append(lid)
            continue
        checked_print += 1
        screen = await screener_prepared_qty(session, job.id, lid)
        cup = await helper_prepared_qty(session, job.id, lid)
        if screen <= 0 or cup <= 0:
            pending_prep.append(lid)

    if unresolved:
        raise HTTPException(
            409,
            "Sample ditolak — klasifikasi line belum resolved (bukan print canonical): "
            + ", ".join(unresolved),
        )
    if pending_prep:
        raise HTTPException(
            409,
            "Sample menunggu Prepare Screen + Prepare Cup READY pada line: "
            + ", ".join(pending_prep),
        )

    if checked_print == 0:
        # Legacy job without scheduled/classified print lines: job-level evidence.
        screen = await session.scalar(
            select(func.coalesce(func.sum(PrepState.qty), 0)).where(
                PrepState.job_id == job.id, PrepState.role == PREP_ROLE_SCREEN
            )
        )
        cup = await session.scalar(
            select(func.coalesce(func.sum(PrepState.qty), 0)).where(
                PrepState.job_id == job.id, PrepState.role == PREP_ROLE_CUP
            )
        )
        if Decimal(screen or 0) <= 0 or Decimal(cup or 0) <= 0:
            raise HTTPException(
                409,
                "Sample membutuhkan Prepare Screen READY dan Prepare Cup READY",
            )
