"""Delivery schedule read model, delivery plan, machine master, report and assignees.

Everything here is derived from V3 production events and master rows. Nothing is
invented: address and courier appear only when an official record carries them.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.production.design import DesignVersion
from app.models.production.event import ProductionEvent
from app.models.production.job import ProductionJob
from app.models.production.operations import (
    DeliveryPlan,
    DeliveryPlanEvent,
    ProductionMachine,
)
from app.models.production.payment import PaymentBypass, PaymentReceiptRef
from app.models.user import User
from app.services.production import engine, permissions as P

WIB = timezone(timedelta(hours=7))
ALLOWED_SLA_DAYS = (1, 3, 5)
URGENT_STATES = {"approved_urgent", "legacy_urgent"}


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def today_wib() -> date:
    return datetime.now(WIB).date()


def add_working_days(start: date, days: int, holidays: set[date] | None = None) -> date:
    """Monday-Saturday count as working days; Sunday and listed holidays are skipped."""
    holidays = holidays or set()
    current = start
    left = days
    while left > 0:
        current += timedelta(days=1)
        if current.weekday() == 6 or current in holidays:
            continue
        left -= 1
    return current


def sla_working_days() -> int:
    days = int(get_settings().v3_sla_working_days)
    return days if days in ALLOWED_SLA_DAYS else 3


async def job_sla(session: AsyncSession, job: ProductionJob, planned: date | None) -> dict:
    """V1 rule: latest(design, payment approval) + N working days; urgent uses manual date only."""
    urgent = (job.urgent_state or "") in URGENT_STATES
    if urgent:
        return {"date": planned.isoformat() if planned else None, "source": "urgent_manual" if planned else "non_final", "urgent": True}
    design_at = await session.scalar(
        select(func.max(DesignVersion.decided_at)).where(
            DesignVersion.job_id == job.id, DesignVersion.status.in_(["approved", "bypassed"])
        )
    )
    pay_receipt = await session.scalar(
        select(func.min(PaymentReceiptRef.created_at)).where(
            PaymentReceiptRef.job_id == job.id,
            PaymentReceiptRef.status == "valid",
            PaymentReceiptRef.evidence_verified.is_(True),
            PaymentReceiptRef.amount > 0,
        )
    )
    pay_bypass = await session.scalar(
        select(func.min(PaymentBypass.created_at)).where(
            PaymentBypass.job_id == job.id, PaymentBypass.active.is_(True)
        )
    )
    pay_at = min([t for t in (pay_receipt, pay_bypass) if t is not None], default=None)
    if design_at is None or pay_at is None:
        return {"date": None, "source": "non_final", "urgent": False}
    anchor = max(design_at, pay_at).astimezone(WIB).date()
    return {
        "date": add_working_days(anchor, sla_working_days()).isoformat(),
        "source": "automatic",
        "urgent": False,
        "working_days": sla_working_days(),
    }


def _payload(ev: ProductionEvent) -> dict:
    try:
        return json.loads(ev.payload_json or "{}")
    except ValueError:
        return {}


async def list_deliveries(
    session: AsyncSession,
    user: User,
    *,
    q: str | None = None,
    status: str | None = None,
    branch: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict:
    """One row per active Surat Jalan that has confirmed Loading (read-only, branch scoped)."""
    engine._require(user, P.JOB_READ)
    from app.authorization.workflow import branch_allowed

    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    branches = (await session.scalars(select(ProductionJob.branch_id).distinct())).all()
    allowed = [b for b in branches if branch_allowed(user, b) and (not branch or b == branch)]
    sj_ids = (
        select(ProductionEvent.job_id, ProductionEvent.accurate_sj_id)
        .join(ProductionJob, ProductionJob.id == ProductionEvent.job_id)
        .where(
            ProductionEvent.event_type == engine.LOADING_EVENT,
            ProductionEvent.accurate_sj_id.is_not(None),
            ProductionJob.branch_id.in_(allowed or [""]),
        )
        .distinct()
    )
    if q and q.strip():
        like = _like(q.strip())
        sj_ids = sj_ids.where(
            or_(
                ProductionJob.accurate_so_number.ilike(like, escape="\\"),
                ProductionJob.customer_name.ilike(like, escape="\\"),
                ProductionEvent.accurate_sj_number.ilike(like, escape="\\"),
            )
        )
    pairs = [(j, s) for j, s in (await session.execute(sj_ids)).all()]
    if not pairs:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "has_more": False, "coverage": _coverage()}
    job_ids = sorted({j for j, _ in pairs})
    jobs = {j.id: j for j in (await session.scalars(select(ProductionJob).where(ProductionJob.id.in_(job_ids)))).all()}
    events = (
        await session.scalars(
            select(ProductionEvent).where(
                ProductionEvent.job_id.in_(job_ids),
                ProductionEvent.event_type.in_(
                    [engine.LOADING_EVENT, engine.LOADING_CANCEL_EVENT, "pod", "sj_cancelled"]
                ),
                ProductionEvent.accurate_sj_id.is_not(None),
            )
        )
    ).all()
    by_sj: dict[tuple, list] = defaultdict(list)
    for ev in events:
        by_sj[(ev.job_id, ev.accurate_sj_id)].append(ev)
    plans = {
        (p.job_id, p.accurate_sj_id): p
        for p in (await session.scalars(select(DeliveryPlan).where(DeliveryPlan.job_id.in_(job_ids)))).all()
    }
    courier_ids = {p.courier_user_id for p in plans.values() if p.courier_user_id}
    couriers = {}
    if courier_ids:
        couriers = {u.id: u.display_name for u in (await session.scalars(select(User).where(User.id.in_(courier_ids)))).all()}
    from app.models.production.prep import JobLineQty

    po_totals = dict(
        (await session.execute(
            select(JobLineQty.job_id, func.coalesce(func.sum(JobLineQty.po_qty), 0))
            .where(JobLineQty.job_id.in_(job_ids))
            .group_by(JobLineQty.job_id)
        )).all()
    )
    cancelled_sj = {k for k, v in by_sj.items() if any(e.event_type == "sj_cancelled" for e in v)}
    job_delivered: dict[int, Decimal] = defaultdict(Decimal)
    for (jid, sid), evs_ in by_sj.items():
        if (jid, sid) in cancelled_sj:
            continue
        job_delivered[jid] += sum((Decimal(e.qty_physical or 0) for e in evs_ if e.event_type == "pod"), Decimal(0))
    sla_cache: dict[int, dict] = {}
    today = today_wib()
    rows = []
    for (job_id, sj_id) in sorted(set(pairs), key=lambda p: (-p[0], p[1])):
        job = jobs[job_id]
        evs = by_sj[(job_id, sj_id)]
        cancelled = any(e.event_type == "sj_cancelled" for e in evs)
        number = next((e.accurate_sj_number for e in evs if e.event_type == engine.LOADING_EVENT and e.accurate_sj_number), None)
        loaded = sum((Decimal(e.qty_physical or 0) for e in evs if e.event_type == engine.LOADING_EVENT), Decimal(0))
        loaded -= sum((Decimal(e.qty_physical or 0) for e in evs if e.event_type == engine.LOADING_CANCEL_EVENT), Decimal(0))
        loaded = max(loaded, Decimal(0))
        pods = [e for e in evs if e.event_type == "pod"]
        delivered = sum((Decimal(e.qty_physical or 0) for e in pods), Decimal(0))
        sj_lines: dict[str, Decimal] = {}
        for e in sorted((e for e in evs if e.event_type == engine.LOADING_EVENT), key=lambda e: e.id):
            base = _payload(e).get("authorized_base")
            if base is not None and e.accurate_sj_line_id:
                sj_lines[e.accurate_sj_line_id] = Decimal(str(base))
        sj_qty = sum(sj_lines.values(), Decimal(0))
        plan = plans.get((job_id, sj_id))
        planned = plan.planned_date if plan else None
        if cancelled:
            delivery_status = "dibatalkan"
        elif sj_qty > 0 and delivered >= sj_qty:
            delivery_status = "terkirim"
        elif delivered > 0:
            delivery_status = "sebagian"
        else:
            delivery_status = "belum_dikirim"
        if delivery_status in ("terkirim", "dibatalkan"):
            schedule_status = delivery_status
        elif planned is None:
            schedule_status = "belum_dijadwalkan"
        elif planned == today:
            schedule_status = "hari_ini"
        elif planned < today:
            schedule_status = "terjadwal" if job.buffer_stock else "terlambat"
        else:
            schedule_status = "terjadwal"
        if job_id not in sla_cache:
            sla_cache[job_id] = await job_sla(session, job, planned)
        sla = dict(sla_cache[job_id])
        if sla.get("urgent"):
            sla = await job_sla(session, job, planned)
        last_pod = pods[-1] if pods else None
        receiver = None
        if last_pod and (last_pod.reason or "").startswith("receiver:"):
            receiver = last_pod.reason[len("receiver:"):].strip() or None
        rows.append(
            {
                "job_id": job_id,
                "accurate_so_number": job.accurate_so_number,
                "accurate_sj_id": sj_id,
                "accurate_sj_number": number,
                "customer_name": job.customer_name,
                "branch_id": job.branch_id,
                "planned_date": planned.isoformat() if planned else None,
                "courier_user_id": plan.courier_user_id if plan else None,
                "courier_name": couriers.get(plan.courier_user_id) if plan and plan.courier_user_id else None,
                "qty_sj": str(sj_qty),
                "qty_loaded": str(loaded),
                "qty_delivered": str(delivered),
                "qty_remaining_to_deliver": str(max(loaded - delivered, Decimal(0))),
                "qty_remaining_to_load": str(max(sj_qty - loaded, Decimal(0))),
                "delivery_status": delivery_status,
                "schedule_status": schedule_status,
                "sla": sla,
                "urgent": (job.urgent_state or "") in URGENT_STATES,
                "buffer_stock": bool(job.buffer_stock),
                "recipient_name": receiver,
                "address": None,
                "po_qty_total": str(Decimal(po_totals.get(job_id) or 0)),
                "po_qty_delivered": str(job_delivered[job_id]),
                "po_complete": bool(
                    Decimal(po_totals.get(job_id) or 0) > 0
                    and job_delivered[job_id] >= Decimal(po_totals.get(job_id) or 0)
                ),
            }
        )
    if status:
        rows = [r for r in rows if r["schedule_status"] == status or r["delivery_status"] == status]
    if date_from:
        rows = [r for r in rows if r["planned_date"] and r["planned_date"] >= date_from.isoformat()]
    if date_to:
        rows = [r for r in rows if r["planned_date"] and r["planned_date"] <= date_to.isoformat()]
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "items": rows[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": start + page_size < total,
        "coverage": _coverage(),
    }


def _coverage() -> dict:
    return {
        "scope": "Surat Jalan dengan Loading terkonfirmasi pada job V3",
        "address": "Belum tersedia; bukan syarat jadwal, Loading, atau POD",
    }


async def plan_delivery(
    session: AsyncSession,
    user: User,
    job_id: int,
    *,
    accurate_sj_id: str,
    planned_date: date,
    courier_user_id: int | None,
    reason: str | None,
    idempotency_key: str,
) -> dict:
    engine._require(user, P.DELIVERY_MANAGE)
    sj_id = (accurate_sj_id or "").strip()
    key = (idempotency_key or "").strip()
    if not sj_id or not key:
        raise HTTPException(422, "SJ dan idempotency key wajib")
    job = await engine.get_job(session, job_id)
    engine._branch(user, job.branch_id)
    locked = await session.scalar(
        select(ProductionJob).where(ProductionJob.id == job.id).with_for_update()
    )
    if locked is None:
        raise HTTPException(404, "Production job tidak ditemukan")
    prior = await session.scalar(
        select(DeliveryPlanEvent).where(
            DeliveryPlanEvent.job_id == job.id, DeliveryPlanEvent.idempotency_key == key
        )
    )
    if prior is not None:
        plan = await session.get(DeliveryPlan, prior.plan_id)
        if (
            plan is None
            or plan.accurate_sj_id != sj_id
            or prior.new_date != planned_date
            or prior.new_courier_user_id != courier_user_id
        ):
            raise HTTPException(409, "Idempotency key payload tidak cocok")
        return _plan_dict(plan, prior, replay=True)
    if await session.scalar(
        select(func.count()).select_from(ProductionEvent).where(
            ProductionEvent.job_id == job.id,
            ProductionEvent.event_type == "sj_cancelled",
            ProductionEvent.accurate_sj_id == sj_id,
        )
    ):
        raise HTTPException(409, "SJ sudah dibatalkan")
    loaded = await engine._net_confirmed_loading_sum(session, job.id, accurate_sj_id=sj_id)
    if loaded <= 0:
        raise HTTPException(409, "SJ belum memiliki Loading terkonfirmasi")
    delivered = Decimal(
        await session.scalar(
            select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
                ProductionEvent.job_id == job.id,
                ProductionEvent.event_type == "pod",
                ProductionEvent.accurate_sj_id == sj_id,
            )
        )
        or 0
    )
    if delivered >= loaded:
        raise HTTPException(409, "SJ sudah selesai dikirim")
    if courier_user_id is not None:
        courier = await session.get(User, courier_user_id)
        if courier is None or not courier.is_active:
            raise HTTPException(422, "Kurir harus user aktif")
        if job.branch_id not in (courier.branch_ids or []) or "production.delivery.manage" not in (courier.permissions or []):
            from app.authorization.evaluator import Resource, evaluate
            from app.authorization.service import load_access

            try:
                access = await load_access(session, courier.id, lock=False)
                ok = evaluate(access, "delivery.pod.record", Resource(job.branch_id, None)).allowed
            except Exception:
                ok = False
            if not ok:
                raise HTTPException(409, "Kurir tidak berwenang pada cabang job ini")
    plan = await session.scalar(
        select(DeliveryPlan)
        .where(DeliveryPlan.job_id == job.id, DeliveryPlan.accurate_sj_id == sj_id)
        .with_for_update()
    )
    previous_date = plan.planned_date if plan else None
    previous_courier = plan.courier_user_id if plan else None
    if plan is not None and not (reason or "").strip():
        raise HTTPException(422, "Alasan jadwal ulang wajib diisi")
    if plan is None:
        plan = DeliveryPlan(
            job_id=job.id, accurate_sj_id=sj_id, branch_id=job.branch_id,
            planned_date=planned_date, courier_user_id=courier_user_id,
        )
        session.add(plan)
        await session.flush()
    else:
        plan.planned_date = planned_date
        plan.courier_user_id = courier_user_id
    event = DeliveryPlanEvent(
        plan_id=plan.id, job_id=job.id, previous_date=previous_date, new_date=planned_date,
        previous_courier_user_id=previous_courier, new_courier_user_id=courier_user_id,
        reason=(reason or "").strip() or None, idempotency_key=key, actor_user_id=user.id,
    )
    session.add(event)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Jadwal pengiriman bentrok; ulangi permintaan") from exc
    await session.refresh(plan)
    await session.refresh(event)
    return _plan_dict(plan, event, replay=False)


def _plan_dict(plan: DeliveryPlan, event: DeliveryPlanEvent, *, replay: bool) -> dict:
    return {
        "plan_id": plan.id,
        "job_id": plan.job_id,
        "accurate_sj_id": plan.accurate_sj_id,
        "planned_date": plan.planned_date.isoformat(),
        "courier_user_id": plan.courier_user_id,
        "event_id": event.id,
        "previous_date": event.previous_date.isoformat() if event.previous_date else None,
        "rescheduled": event.previous_date is not None,
        "replay": replay,
    }


async def list_plan_history(session: AsyncSession, user: User, job_id: int, accurate_sj_id: str) -> list[dict]:
    engine._require(user, P.JOB_READ)
    job = await engine.get_job(session, job_id)
    engine._branch(user, job.branch_id)
    rows = (
        await session.scalars(
            select(DeliveryPlanEvent)
            .join(DeliveryPlan, DeliveryPlan.id == DeliveryPlanEvent.plan_id)
            .where(DeliveryPlan.job_id == job_id, DeliveryPlan.accurate_sj_id == accurate_sj_id)
            .order_by(DeliveryPlanEvent.id)
        )
    ).all()
    return [
        {
            "id": r.id,
            "previous_date": r.previous_date.isoformat() if r.previous_date else None,
            "new_date": r.new_date.isoformat(),
            "reason": r.reason,
            "actor_user_id": r.actor_user_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def _machine_dict(m: ProductionMachine) -> dict:
    return {
        "id": m.id,
        "branch_id": m.branch_id,
        "name": m.name,
        "kind": m.kind,
        "capacity_per_shift": str(m.capacity_per_shift),
        "shifts_per_day": m.shifts_per_day,
        "capacity_per_day": str(Decimal(m.capacity_per_shift) * int(m.shifts_per_day or 1)),
        "active": m.active,
    }


async def list_machines(session: AsyncSession, user: User, *, branch: str | None = None) -> dict:
    engine._require(user, P.JOB_READ)
    from app.authorization.workflow import branch_allowed

    rows = (await session.scalars(select(ProductionMachine).order_by(ProductionMachine.branch_id, ProductionMachine.name))).all()
    items = [_machine_dict(m) for m in rows if branch_allowed(user, m.branch_id) and (not branch or m.branch_id == branch)]
    return {
        "items": items,
        "default_capacity_per_shift": str(get_settings().v3_default_shift_capacity),
        "enforced": bool(items),
    }


async def create_machine(
    session: AsyncSession, user: User, *, branch_id: str, name: str, kind: str,
    capacity_per_shift: Decimal | None, shifts_per_day: int,
) -> dict:
    engine._require(user, P.SCHEDULE_MANAGE)
    engine._branch(user, branch_id)
    name = (name or "").strip()
    if not name:
        raise HTTPException(422, "Nama mesin wajib")
    if kind not in ("auto", "semi_auto"):
        raise HTTPException(422, "Jenis mesin tidak valid")
    cap = capacity_per_shift if capacity_per_shift is not None else Decimal(get_settings().v3_default_shift_capacity)
    if cap <= 0 or shifts_per_day < 1:
        raise HTTPException(422, "Kapasitas dan shift harus > 0")
    row = ProductionMachine(
        branch_id=branch_id, name=name, kind=kind, capacity_per_shift=cap,
        shifts_per_day=shifts_per_day, created_by=user.id,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Mesin dengan nama ini sudah ada pada cabang") from exc
    await session.refresh(row)
    return _machine_dict(row)


async def update_machine(
    session: AsyncSession, user: User, machine_id: int, *, capacity_per_shift: Decimal | None,
    shifts_per_day: int | None, active: bool | None, kind: str | None,
) -> dict:
    engine._require(user, P.SCHEDULE_MANAGE)
    row = await session.scalar(
        select(ProductionMachine).where(ProductionMachine.id == machine_id).with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Mesin tidak ditemukan")
    engine._branch(user, row.branch_id)
    if capacity_per_shift is not None:
        if capacity_per_shift <= 0:
            raise HTTPException(422, "Kapasitas harus > 0")
        row.capacity_per_shift = capacity_per_shift
    if shifts_per_day is not None:
        if shifts_per_day < 1:
            raise HTTPException(422, "Shift harus >= 1")
        row.shifts_per_day = shifts_per_day
    if kind is not None:
        if kind not in ("auto", "semi_auto"):
            raise HTTPException(422, "Jenis mesin tidak valid")
        row.kind = kind
    if active is not None:
        row.active = active
    await session.commit()
    await session.refresh(row)
    return _machine_dict(row)


async def production_report(
    session: AsyncSession, user: User, *, branch: str | None, date_from: date | None, date_to: date | None
) -> dict:
    """Aggregate of official production events. Physical cups = pass 1 only (no pass summing)."""
    engine._require(user, P.JOB_READ)
    from app.authorization.workflow import branch_allowed

    branches = (await session.scalars(select(ProductionJob.branch_id).distinct())).all()
    allowed = [b for b in branches if branch_allowed(user, b) and (not branch or b == branch)]
    day = func.date(func.timezone("Asia/Jakarta", ProductionEvent.created_at))
    pass_no = func.coalesce(ProductionEvent.color_pass, engine.PHYSICAL_CUP_COLOR_PASS)
    kinds = {
        "output": (engine.OUTPUT_EVENT_TYPES, True),
        "reject": (engine.REJECT_EVENT_TYPES, True),
        "packing": (engine.PACKING_EVENT_TYPES, False),
        "loading": ({engine.LOADING_EVENT}, False),
        "loading_cancelled": ({engine.LOADING_CANCEL_EVENT}, False),
        "pod": ({"pod"}, False),
    }
    totals: dict[str, Decimal] = {}
    per_branch: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    per_day: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for name, (types, physical_only) in kinds.items():
        conds = [
            ProductionEvent.event_type.in_(list(types)),
            ProductionJob.branch_id.in_(allowed or [""]),
        ]
        if physical_only:
            conds.append(pass_no == engine.PHYSICAL_CUP_COLOR_PASS)
        if name == "pod":
            cancelled = select(ProductionEvent.job_id, ProductionEvent.accurate_sj_id).where(
                ProductionEvent.event_type == "sj_cancelled"
            )
            conds.append(
                tuple_(ProductionEvent.job_id, ProductionEvent.accurate_sj_id).notin_(cancelled)
            )
        if date_from:
            conds.append(day >= date_from)
        if date_to:
            conds.append(day <= date_to)
        res = await session.execute(
            select(ProductionJob.branch_id, day, func.coalesce(func.sum(ProductionEvent.qty_physical), 0))
            .join(ProductionJob, ProductionJob.id == ProductionEvent.job_id)
            .where(and_(*conds))
            .group_by(ProductionJob.branch_id, day)
        )
        totals[name] = Decimal(0)
        for b, d, qty in res.all():
            qty = Decimal(qty or 0)
            totals[name] += qty
            per_branch[b][name] += qty
            per_day[d.isoformat()][name] += qty
    totals["loading_net"] = totals["loading"] - totals["loading_cancelled"]
    return {
        "source": "production_events",
        "basis": "qty fisik (color_pass 1 untuk output/reject); pass lain tidak dijumlahkan",
        "from": date_from.isoformat() if date_from else None,
        "to": date_to.isoformat() if date_to else None,
        "totals": {k: str(v) for k, v in totals.items()},
        "by_branch": {b: {k: str(v) for k, v in m.items()} for b, m in sorted(per_branch.items())},
        "by_day": {d: {k: str(v) for k, v in m.items()} for d, m in sorted(per_day.items())},
    }


async def list_assignees(session: AsyncSession, user: User, *, kind: str, branch: str) -> dict:
    """Official users eligible to receive operator or courier work in one branch."""
    engine._require(user, P.JOB_READ)
    engine._branch(user, branch)
    capability, legacy = (
        ("output.record", "production.output.confirm")
        if kind == "operator"
        else ("delivery.pod.record", "production.delivery.manage")
    )
    from app.authorization.evaluator import Resource, evaluate
    from app.authorization.service import load_access

    users = (await session.scalars(select(User).where(User.is_active.is_(True)).order_by(User.display_name).limit(500))).all()
    out = []
    for u in users:
        ok = legacy in (u.permissions or []) and branch in (u.branch_ids or [])
        if not ok:
            try:
                ok = evaluate(await load_access(session, u.id, lock=False), capability, Resource(branch, None)).allowed
            except Exception:
                ok = False
        if ok:
            out.append({"id": u.id, "display_name": u.display_name, "username": u.username})
    return {"kind": kind, "branch_id": branch, "items": out}


async def list_unsynced_payment_pos(
    session: AsyncSession, user: User, gateway, *, page: int, limit: int, keyword: str
) -> dict:
    """Accurate POs that have no V3 job yet. Read-only: no job or receipt row is created.

    The gateway paginates all branches, so the filter applies to the returned page;
    callers page onward until has_more is false.
    """
    engine._require(user, P.JOB_READ)
    from app.api.production_inbox import _scoped_inbox
    from app.authorization.workflow import context
    from app.core.security import user_can_access_branch
    from app.services.accurate_read_gateway import list_sales_orders

    ctx = context(user)
    if ctx and not ctx.access.director:
        data = await _scoped_inbox(gateway, session, user, page, limit, keyword)
        rows = data["rows"]
        meta = {k: data[k] for k in ("has_more", "scan_incomplete") if k in data}
    else:
        data = await list_sales_orders(gateway, page=page, limit=limit, keyword=keyword)
        rows = [r for r in data["rows"] if user_can_access_branch(user, r.get("branch_id"))]
        meta = {"has_more": page * limit < int(data.get("total") or 0), "scan_incomplete": False}
    numbers = [str(r.get("po_number")) for r in rows if r.get("po_number")]
    existing = set(
        (await session.scalars(select(ProductionJob.accurate_so_number).where(ProductionJob.accurate_so_number.in_(numbers)))).all()
    ) if numbers else set()
    items = [
        {
            "po_number": r.get("po_number"),
            "customer_name": r.get("customer_name"),
            "branch_id": r.get("branch_id"),
            "has_job": False,
            "payment_status": "pending",
            "receipt_count": 0,
            "verified_amount": None,
            "note": "Belum ada job V3; tidak ada penerimaan tercatat",
        }
        for r in rows
        if str(r.get("po_number")) not in existing
    ]
    return {"items": items, "page": page, "limit": limit, "source": "accurate_gateway", **meta}


async def acknowledge_qty_drift(
    session: AsyncSession, user: User, job_id: int, *, so_line_id: str, reason: str, idempotency_key: str
) -> dict:
    """Record that a person reviewed an Accurate qty change. The V3 PO qty is never rewritten."""
    from app.models.production.prep import JobLineQty

    engine._require(user, P.SCHEDULE_MANAGE)
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise HTTPException(422, "Alasan rekonsiliasi wajib")
    job = await engine.get_job(session, job_id)
    engine._branch(user, job.branch_id)
    job = await engine._lock_payment_job(session, user, job)
    prior = await session.scalar(
        select(ProductionEvent).where(ProductionEvent.idempotency_key == idempotency_key)
    )
    if prior is not None:
        if prior.job_id != job.id or prior.so_line_id != so_line_id or prior.event_type != "qty_drift_ack":
            raise HTTPException(409, "Idempotency key dipakai untuk permintaan lain")
        return {"id": prior.id, "replay": True}
    line = await session.scalar(
        select(JobLineQty).where(JobLineQty.job_id == job.id, JobLineQty.so_line_id == so_line_id)
    )
    if line is None or line.source_qty is None:
        raise HTTPException(409, "Tidak ada perbedaan qty Accurate untuk line ini")
    ev = ProductionEvent(
        job_id=job.id,
        event_type="qty_drift_ack",
        so_line_id=so_line_id,
        idempotency_key=idempotency_key,
        actor_user_id=user.id,
        reason=reason,
        payload_json=json.dumps({"po_qty": str(line.po_qty), "source_qty": str(line.source_qty)}),
    )
    session.add(ev)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Idempotency key duplikat") from exc
    return {"id": ev.id, "replay": False}


async def list_payroll_runs(session: AsyncSession, user: User, *, limit: int = 50) -> dict:
    """Read-only list of official payroll runs visible to the user; no amounts are computed here."""
    from app.authorization.workflow import branch_allowed
    from app.models.production.payroll import PayrollLine, PayrollRun

    engine._require(user, P.PAYROLL_READ)
    runs = (await session.scalars(select(PayrollRun).order_by(PayrollRun.id.desc()).limit(limit * 3))).all()
    items = []
    for r in runs:
        if r.branch_id and not branch_allowed(user, r.branch_id):
            continue
        total = await session.scalar(
            select(func.coalesce(func.sum(PayrollLine.amount_gross), 0)).where(PayrollLine.run_id == r.id)
        )
        items.append(
            {
                "id": r.id,
                "status": r.status,
                "branch_id": r.branch_id,
                "period_start": str(r.period_start),
                "period_end": str(r.period_end),
                "amount_gross_total": str(total),
            }
        )
        if len(items) >= limit:
            break
    return {"items": items}


def _authorized_base(ev) -> Decimal | None:
    raw = _payload(ev).get("authorized_base")
    if raw is None:
        return None
    try:
        qty = Decimal(str(raw))
    except Exception:
        return None
    return qty if qty > 0 else None


def _explicit_pod_lines(ev) -> list[dict] | None:
    raw = _payload(ev).get("lines")
    if not isinstance(raw, list) or not raw:
        return None
    rows = []
    for row in raw:
        if not isinstance(row, dict) or row.get("so_line_id") is None or row.get("qty_physical") is None:
            return None
        try:
            qty = Decimal(str(row["qty_physical"]))
        except Exception:
            return None
        rows.append({"so_line_id": str(row["so_line_id"]), "qty": qty})
    return rows


def _delivered_for_line(evs, lid: str, conflicts: list[str]) -> tuple[Decimal | None, bool, bool]:
    """POD qty for one PO line.

    A single-item SJ with a proven line uses the POD qty, capped by the document qty.
    A multi-item SJ uses only an actual per-line receipt stored on the POD.
    Document-qty ratios are never treated as received qty. Unknown stays unknown.
    """
    cancelled = {e.accurate_sj_id for e in evs if e.event_type == "sj_cancelled"}
    doc: dict[str, dict[str, Decimal]] = {}
    unmapped: set[str] = set()
    touched: dict[str, set] = defaultdict(set)
    for e in evs:
        if e.event_type != engine.LOADING_EVENT or not e.accurate_sj_id or e.accurate_sj_id in cancelled:
            continue
        if e.so_line_id:
            touched[e.accurate_sj_id].add(e.so_line_id)
        base = _authorized_base(e)
        if not e.so_line_id or base is None or (e.so_line_id in doc.get(e.accurate_sj_id, {}) and doc[e.accurate_sj_id][e.so_line_id] != base):
            unmapped.add(e.accurate_sj_id)
        else:
            doc.setdefault(e.accurate_sj_id, {})[e.so_line_id] = base
    total = Decimal(0)
    known = False
    unknown = False
    for e in evs:
        if e.event_type != "pod" or not e.accurate_sj_id or e.accurate_sj_id in cancelled:
            continue
        sj = e.accurate_sj_id
        if lid not in touched.get(sj, set()):
            continue
        explicit = _explicit_pod_lines(e)
        if explicit is not None:
            known = True
            total += sum((row["qty"] for row in explicit if row["so_line_id"] == lid), Decimal(0))
            doc_qty = doc.get(sj, {}).get(lid)
            if doc_qty is not None and total > doc_qty:
                conflicts.append(f"POD item {lid} melebihi qty dokumen SJ {sj}")
                unknown = True
            continue
        docmap = doc.get(sj) or {}
        if sj not in unmapped and len(touched.get(sj, ())) == 1 and lid in docmap:
            pod_qty = Decimal(e.qty_physical or 0)
            if pod_qty > docmap[lid]:
                conflicts.append(f"POD {pod_qty} melebihi qty dokumen line {lid} pada SJ {sj}")
                unknown = True
            else:
                known = True
                total += pod_qty
            continue
        unknown = True
    if known and not unknown:
        return total, False, True
    return None, True, False


def _apply_buffer_line(item: dict, ln, evs, assignments, render) -> None:
    """Split gesut work from order fulfillment. Non-print is not a gesut backlog."""
    lid = ln.so_line_id
    total_qty = Decimal(ln.po_qty)
    process = (ln.production_process or "").strip()
    if process not in {"print", "non_print"}:
        process = "unknown"
    item["production_process"] = None if process == "unknown" else process
    conflicts: list[str] = []
    required = engine.required_color_passes_from_assignments(assignments, so_line_id=lid)
    nets = []
    for pass_no in sorted(required):
        def _pass(ev, pass_no=pass_no):
            return int(ev.color_pass or engine.PHYSICAL_CUP_COLOR_PASS) == pass_no
        ok = sum((Decimal(e.qty_physical or 0) for e in evs if e.so_line_id == lid and e.event_type in engine.HELPER_VERIFIED_EVENT_TYPES and _pass(e)), Decimal(0))
        bad = sum((Decimal(e.qty_physical or 0) for e in evs if e.so_line_id == lid and e.event_type in engine.REJECT_EVENT_TYPES and _pass(e)), Decimal(0))
        nets.append(ok - bad)
    if process == "non_print":
        done: Decimal | None = Decimal(0)
        remaining: Decimal | None = Decimal(0)
        target: Decimal | None = Decimal(0)
    elif process == "unknown":
        done = remaining = target = None
    elif any(n < 0 for n in nets):
        conflicts.append("reject melebihi output helper-verified")
        done = remaining = None
        target = total_qty
    else:
        done = min(nets) if nets else Decimal(0)
        target = total_qty
        if done > total_qty:
            conflicts.append(f"gesut {done} melebihi qty PO {total_qty}")
            done = remaining = None
        else:
            remaining = total_qty - done
    packed_events = [e for e in evs if e.so_line_id == lid and e.event_type in engine.PACKING_EVENT_TYPES]
    packed = sum((Decimal(e.qty_physical or 0) for e in packed_events), Decimal(0))
    loaded_gross = sum((Decimal(e.qty_physical or 0) for e in evs if e.so_line_id == lid and e.event_type == engine.LOADING_EVENT), Decimal(0))
    loaded_cancel = sum((Decimal(e.qty_physical or 0) for e in evs if e.so_line_id == lid and e.event_type == engine.LOADING_CANCEL_EVENT), Decimal(0))
    if loaded_cancel > loaded_gross:
        conflicts.append(f"pembatalan loading {loaded_cancel} melebihi loading {loaded_gross}")
        loaded: Decimal | None = None
    else:
        loaded = loaded_gross - loaded_cancel
    ready_base: Decimal | None
    if process == "print":
        if not packed_events or done is None:
            ready_base = None
        elif packed > done:
            conflicts.append(f"packing {packed} melebihi output cetak sah {done}")
            ready_base = None
        else:
            ready_base = packed
    elif process == "non_print":
        if not packed_events:
            ready_base = None
        elif packed > total_qty:
            conflicts.append(f"packing {packed} melebihi qty PO {total_qty}")
            ready_base = None
        else:
            ready_base = packed
    else:
        ready_base = None
    if ready_base is None:
        ready = None
        if (
            loaded is not None
            and loaded > 0
            and process in {"print", "non_print"}
            and not packed_events
        ):
            conflicts.append(f"loading {loaded} tanpa packing sah")
    elif loaded is None or loaded > ready_base:
        if loaded is not None and loaded > ready_base:
            conflicts.append(f"loading {loaded} melebihi packing sah {ready_base}")
        ready = None
    else:
        ready = ready_base - loaded
    delivered, pod_unknown, _proven = _delivered_for_line(evs, lid, conflicts)
    item["gesut_target"] = render(target) if target is not None else None
    item["done_gesut"] = render(done) if done is not None else None
    item["remaining_gesut"] = render(remaining) if remaining is not None else None
    item["ready_warehouse"] = render(ready) if ready is not None else None
    item["ready_state"] = "VERIFIED" if ready is not None else "UNVERIFIED"
    item["delivered"] = render(delivered) if delivered is not None and not pod_unknown else None
    item["delivered_state"] = "UNVERIFIED" if pod_unknown or delivered is None else "VERIFIED"
    item["integrity"] = "INTEGRITY_CONFLICT" if conflicts else None
    item["integrity_detail"] = "; ".join(conflicts) or None
    if conflicts:
        item["buffer_status"] = "INTEGRITY_CONFLICT"
    elif process == "non_print":
        if delivered is not None and delivered >= total_qty:
            movement = "Selesai diambil/terkirim"
        elif delivered is not None and delivered > 0:
            movement = "Sebagian diambil/terkirim"
        elif ready is not None and ready > 0:
            movement = "Ready gudang"
        else:
            movement = None
        item["buffer_status"] = "Tidak perlu gesut" if movement is None else f"Tidak perlu gesut · {movement}"
    elif process == "unknown":
        item["buffer_status"] = None
    elif delivered is not None and delivered >= total_qty:
        item["buffer_status"] = "Selesai diambil/terkirim"
    elif delivered is not None and delivered > 0:
        item["buffer_status"] = "Sebagian diambil/terkirim"
    elif ready is not None and ready > 0:
        item["buffer_status"] = "Ready gudang"
    elif done is not None and done > 0:
        item["buffer_status"] = "Proses gesut"
    else:
        item["buffer_status"] = "Belum mulai"


def _buffer_totals(items: list[dict]) -> dict:
    """Page-independent sums. Unknown figures stay null and are never added as zero."""
    fulfillment = gesut = remaining = Decimal(0)
    fulfillment_ok = gesut_ok = remaining_ok = True
    outstanding = unverified = Decimal(0)
    saw_verified = False
    for row in items:
        qty = row.get("fulfillment_qty")
        if qty is None:
            fulfillment_ok = False
        else:
            fulfillment += Decimal(qty)
        if row.get("gesut_target") is None:
            gesut_ok = False
        else:
            gesut += Decimal(row["gesut_target"])
        if row.get("remaining_gesut") is None:
            remaining_ok = False
        else:
            remaining += Decimal(row["remaining_gesut"])
        if row.get("delivered_state") == "VERIFIED" and row.get("delivered") is not None and qty is not None:
            saw_verified = True
            gap = Decimal(qty) - Decimal(row["delivered"])
            outstanding += gap if gap > 0 else Decimal(0)
        elif qty is not None:
            unverified += Decimal(qty)
    def _s(v: Decimal) -> str:
        return format(v.normalize(), "f") if v != v.to_integral_value() else str(int(v))
    return {
        "fulfillment_qty": _s(fulfillment) if fulfillment_ok else None,
        "gesut_target": _s(gesut) if gesut_ok else None,
        "remaining_gesut": _s(remaining) if remaining_ok else None,
        "fulfillment_outstanding_verified": _s(outstanding) if saw_verified else None,
        "fulfillment_unverified_qty": _s(unverified),
    }


async def list_production_schedule(
    session: AsyncSession,
    user: User,
    *,
    q: str | None = None,
    branch: str | None = None,
    bucket: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 50,
    sort: str = "so_asc",
) -> dict:
    """Jadwal Produksi read model from PostgreSQL print lines (not Inbox pages).

    One response row per print line without assignment, or per remaining assignment.
    Totals never invent print from unknown/non_print. GET never syncs Accurate.
    """
    from app.authorization.workflow import branch_allowed
    from app.models.production.prep import JobLineQty
    from app.models.production.schedule import ScheduleAssignment
    from app.services.production.payment_gate import effective_statuses

    engine._require(user, P.JOB_READ)
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    bucket_norm = (bucket or "semua").strip().lower()
    if bucket_norm not in {"semua", "belum_dijadwalkan", "dijadwalkan", "hold"}:
        raise HTTPException(422, "bucket tidak valid")
    sort_norm = (sort or "so_asc").strip().lower()
    if sort_norm not in {"so_asc", "so_desc", "work_date_asc", "work_date_desc"}:
        raise HTTPException(422, "sort tidak valid")

    branches = (await session.scalars(select(ProductionJob.branch_id).distinct())).all()
    allowed = [b for b in branches if branch_allowed(user, b) and (not branch or b == branch)]
    if not allowed:
        note = "no_jobs" if not branches else "no_branch_access"
        return {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "has_more": False,
            "incomplete": False,
            "unverified": {"unknown_print_candidate_lines": 0, "note": note},
            "cancelled_jobs_supported": False,
            "source": "postgresql_job_line_qtys",
        }

    lines_stmt = (
        select(JobLineQty, ProductionJob)
        .join(ProductionJob, ProductionJob.id == JobLineQty.job_id)
        .where(
            JobLineQty.production_process == "print",
            ProductionJob.branch_id.in_(allowed),
        )
    )
    if q and q.strip():
        like = _like(q.strip())
        op_exists = (
            select(ScheduleAssignment.id)
            .where(
                ScheduleAssignment.job_id == JobLineQty.job_id,
                ScheduleAssignment.so_line_id == JobLineQty.so_line_id,
                ScheduleAssignment.operator_name.ilike(like, escape="\\"),
            )
            .exists()
        )
        lines_stmt = lines_stmt.where(
            or_(
                ProductionJob.accurate_so_number.ilike(like, escape="\\"),
                ProductionJob.customer_name.ilike(like, escape="\\"),
                op_exists,
            )
        )
    line_rows = (await session.execute(lines_stmt.order_by(ProductionJob.id.desc(), JobLineQty.id))).all()

    unknown_count = int(
        await session.scalar(
            select(func.count())
            .select_from(JobLineQty)
            .join(ProductionJob, ProductionJob.id == JobLineQty.job_id)
            .where(
                or_(
                    JobLineQty.production_process.is_(None),
                    JobLineQty.production_process == "unknown",
                ),
                ProductionJob.branch_id.in_(allowed),
            )
        )
        or 0
    )

    if not line_rows:
        return {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "has_more": False,
            "incomplete": False,
            "unverified": {
                "unknown_print_candidate_lines": unknown_count,
                "note": "unknown_excluded_from_print_totals",
            },
            "cancelled_jobs_supported": False,
            "source": "postgresql_job_line_qtys",
        }

    job_ids = sorted({job.id for _, job in line_rows})
    line_keys = {(ln.job_id, ln.so_line_id) for ln, _ in line_rows}
    assignments = (
        await session.scalars(
            select(ScheduleAssignment)
            .where(ScheduleAssignment.job_id.in_(job_ids))
            .order_by(ScheduleAssignment.id)
        )
    ).all()
    asg_by_line: dict[tuple[int, str], list] = defaultdict(list)
    for a in assignments:
        if (a.job_id, a.so_line_id) not in line_keys:
            continue
        remaining = Decimal(a.qty_planned or 0) - Decimal(a.qty_cancelled_remaining or 0)
        if remaining <= 0 and a.status in {"cancelled_remaining", "transferred"}:
            continue
        asg_by_line[(a.job_id, a.so_line_id)].append(a)

    output_rows = (
        await session.execute(
            select(
                ProductionEvent.job_id,
                ProductionEvent.so_line_id,
                ProductionEvent.event_type,
                func.coalesce(func.sum(ProductionEvent.qty_physical), 0),
            )
            .where(
                ProductionEvent.job_id.in_(job_ids),
                ProductionEvent.event_type.in_(
                    ["output_confirmed", "output_correction", "reject_verified"]
                ),
                func.coalesce(ProductionEvent.color_pass, 1) == 1,
            )
            .group_by(
                ProductionEvent.job_id,
                ProductionEvent.so_line_id,
                ProductionEvent.event_type,
            )
        )
    ).all()
    done_by_line: dict[tuple[int, str], Decimal] = defaultdict(Decimal)
    for jid, sid, etype, qty in output_rows:
        if not sid:
            continue
        key = (jid, sid)
        amount = Decimal(qty or 0)
        if etype == "reject_verified":
            done_by_line[key] -= amount
        else:
            done_by_line[key] += amount

    payment = await effective_statuses(session, job_ids)
    items: list[dict] = []
    for ln, job in line_rows:
        po_qty = Decimal(ln.po_qty or 0)
        line_asgs = asg_by_line.get((job.id, ln.so_line_id), [])
        # Physical allocation uses color_pass 1 only (cups), never sum multi-pass.
        allocated = sum(
            (
                Decimal(a.qty_planned or 0) - Decimal(a.qty_cancelled_remaining or 0)
                for a in line_asgs
                if int(a.color_pass or 1) == 1
            ),
            Decimal(0),
        )
        done = max(done_by_line.get((job.id, ln.so_line_id), Decimal(0)), Decimal(0))
        hold = ln.source_qty is not None
        design = job.design_status or "pending"
        pay = payment.get(job.id, job.payment_status or "pending")
        if hold:
            monitor = "HOLD"
        elif not line_asgs:
            if design not in {"approved", "bypassed"}:
                monitor = "Belum ACC Design"
            elif pay not in {"approved", "bypassed"}:
                monitor = "Belum ACC Payment"
            else:
                monitor = "Siap Dijadwalkan"
        elif po_qty > 0 and done >= po_qty:
            monitor = "Selesai"
        elif done > 0:
            monitor = "Sedang Produksi"
        else:
            monitor = "Sudah Dijadwalkan"
        bucket_line = (
            "hold"
            if hold
            else ("dijadwalkan" if line_asgs else "belum_dijadwalkan")
        )
        base = {
            "job_id": job.id,
            "accurate_so_number": job.accurate_so_number,
            "customer_name": job.customer_name,
            "branch_id": job.branch_id,
            "so_line_id": ln.so_line_id,
            "accurate_item_id": ln.accurate_item_id,
            "production_process": "print",
            "qty_print_po": str(po_qty),
            "qty_allocated": str(allocated),
            "qty_printed_done": str(done),
            "qty_unallocated": str(max(po_qty - allocated, Decimal(0))),
            "qty_unprinted": str(max(po_qty - done, Decimal(0))),
            "hold": hold,
            "hold_reason": "qty_drift" if hold else None,
            "design_status": design,
            "payment_status": pay,
            "schedule_bucket": bucket_line,
            "schedule_monitor_status": monitor,
            "scheduling_allowed": (
                not hold
                and design in {"approved", "bypassed"}
                and pay in {"approved", "bypassed"}
            ),
            "urgent": (job.urgent_state or "") in URGENT_STATES,
            "buffer_stock": job.buffer_stock,
            "processing_status": job.processing_status,
        }
        display_asgs = line_asgs or [None]
        for a in display_asgs:
            if a is None:
                work_date = None
                row = {
                    **base,
                    "row_kind": "unassigned",
                    "assignment_id": None,
                    "color_pass": None,
                    "operator_name": None,
                    "machine_name": None,
                    "work_date": None,
                    "assignment_qty_planned": "0",
                    "assignment_qty_confirmed": "0",
                    "assignment_status": None,
                    "row_key": f"{job.id}:{ln.so_line_id}:empty",
                }
            else:
                work_date = a.work_date
                if date_from and work_date and work_date < date_from:
                    continue
                if date_to and work_date and work_date > date_to:
                    continue
                row = {
                    **base,
                    "row_kind": "assignment",
                    "assignment_id": a.id,
                    "color_pass": int(a.color_pass or 1),
                    "operator_name": a.operator_name,
                    "machine_name": a.machine_name,
                    "work_date": work_date.isoformat() if work_date else None,
                    "assignment_qty_planned": str(
                        Decimal(a.qty_planned or 0) - Decimal(a.qty_cancelled_remaining or 0)
                    ),
                    "assignment_qty_confirmed": str(Decimal(a.qty_confirmed or 0)),
                    "assignment_status": a.status,
                    "row_key": f"{job.id}:{ln.so_line_id}:a{a.id}",
                }
            if a is None and (date_from or date_to):
                # Unassigned active print work stays visible outside date windows.
                pass
            if bucket_norm == "hold" and not hold:
                continue
            if bucket_norm == "belum_dijadwalkan" and line_asgs:
                continue
            if bucket_norm == "dijadwalkan" and not line_asgs:
                continue
            if bucket_norm == "dijadwalkan" and a is None:
                continue
            if bucket_norm == "belum_dijadwalkan" and a is not None:
                continue
            items.append(row)

    if sort_norm == "so_desc":
        items.sort(key=lambda r: (r["accurate_so_number"], r["so_line_id"], r["row_key"]), reverse=True)
    elif sort_norm == "work_date_asc":
        items.sort(key=lambda r: (r["work_date"] is None, r["work_date"] or "", r["accurate_so_number"], r["row_key"]))
    elif sort_norm == "work_date_desc":
        items.sort(key=lambda r: (r["work_date"] is None, r["work_date"] or "", r["accurate_so_number"], r["row_key"]), reverse=True)
    else:
        items.sort(key=lambda r: (r["accurate_so_number"], r["so_line_id"], r["row_key"]))

    # Line-level totals: one contribution per print line (not per assignment row).
    line_seen: set[tuple[int, str]] = set()
    summary = {
        "qty_print_po": Decimal(0),
        "qty_allocated": Decimal(0),
        "qty_printed_done": Decimal(0),
        "qty_unallocated": Decimal(0),
        "qty_unprinted": Decimal(0),
        "print_line_count": 0,
        "hold_line_count": 0,
        "unassigned_line_count": 0,
        "assigned_line_count": 0,
    }
    for row in items:
        key = (row["job_id"], row["so_line_id"])
        if key in line_seen:
            continue
        line_seen.add(key)
        summary["print_line_count"] += 1
        summary["qty_print_po"] += Decimal(row["qty_print_po"])
        summary["qty_allocated"] += Decimal(row["qty_allocated"])
        summary["qty_printed_done"] += Decimal(row["qty_printed_done"])
        summary["qty_unallocated"] += Decimal(row["qty_unallocated"])
        summary["qty_unprinted"] += Decimal(row["qty_unprinted"])
        if row["hold"]:
            summary["hold_line_count"] += 1
        if row["row_kind"] == "unassigned":
            summary["unassigned_line_count"] += 1
        else:
            summary["assigned_line_count"] += 1

    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    return {
        "items": page_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": start + page_size < total,
        "incomplete": False,
        "unverified": {
            "unknown_print_candidate_lines": unknown_count,
            "note": "unknown_excluded_from_print_totals",
        },
        "cancelled_jobs_supported": False,
        "source": "postgresql_job_line_qtys",
        "summary": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in summary.items()},
        "qty_semantics": {
            "qty_print_po": "print line po_qty",
            "qty_allocated": "sum active assignment remaining on color_pass=1 only",
            "qty_printed_done": "net pass-1 output events",
            "qty_unallocated": "po - allocated",
            "qty_unprinted": "po - printed_done",
        },
    }


async def list_buffer_monitor(
    session: AsyncSession,
    user: User,
    *,
    q: str | None = None,
    branch: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """One row per PO line of Buffer Stock jobs (read-only, branch scoped).

    Quantities come only from V3 events. A figure without an official source is None
    (rendered "Belum terverifikasi"), never an invented zero.
    """
    from app.authorization.workflow import branch_allowed
    from app.models.production.prep import JobLineQty
    from app.models.production.schedule import ScheduleAssignment

    engine._require(user, P.JOB_READ)
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    branches = (await session.scalars(select(ProductionJob.branch_id).distinct())).all()
    allowed = [b for b in branches if branch_allowed(user, b) and (not branch or b == branch)]
    stmt = select(ProductionJob).where(
        ProductionJob.buffer_stock.is_(True), ProductionJob.branch_id.in_(allowed or [""])
    )
    if q and q.strip():
        like = _like(q.strip())
        stmt = stmt.where(
            or_(
                ProductionJob.accurate_so_number.ilike(like, escape="\\"),
                ProductionJob.customer_name.ilike(like, escape="\\"),
            )
        )
    jobs = (await session.scalars(stmt.order_by(ProductionJob.id.desc()))).all()
    if not jobs:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "has_more": False}
    job_ids = [j.id for j in jobs]
    lines = (
        await session.scalars(
            select(JobLineQty).where(JobLineQty.job_id.in_(job_ids)).order_by(JobLineQty.job_id.desc(), JobLineQty.id)
        )
    ).all()
    rows_spec: list[tuple[ProductionJob, JobLineQty | None]] = []
    by_job: dict[int, list] = defaultdict(list)
    for ln in lines:
        by_job[ln.job_id].append(ln)
    for job in jobs:
        if by_job.get(job.id):
            rows_spec.extend((job, ln) for ln in by_job[job.id])
        else:
            rows_spec.append((job, None))
    total = len(rows_spec)
    all_jobs = sorted({j.id for j, _ in rows_spec})
    if not all_jobs:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "has_more": False, "totals": _buffer_totals([])}
    events = (
        await session.scalars(
            select(ProductionEvent).where(
                ProductionEvent.job_id.in_(all_jobs),
                ProductionEvent.event_type.in_(
                    [
                        *engine.HELPER_VERIFIED_EVENT_TYPES, *engine.REJECT_EVENT_TYPES,
                        *engine.PACKING_EVENT_TYPES, engine.LOADING_EVENT,
                        engine.LOADING_CANCEL_EVENT, "pod", "sj_cancelled",
                    ]
                ),
            )
        )
    ).all()
    asg = (await session.scalars(select(ScheduleAssignment).where(ScheduleAssignment.job_id.in_(all_jobs)))).all()
    ev_by_job: dict[int, list] = defaultdict(list)
    for e in events:
        ev_by_job[e.job_id].append(e)
    asg_by_job: dict[int, list] = defaultdict(list)
    for a in asg:
        asg_by_job[a.job_id].append(a)

    def _s(v: Decimal) -> str:
        return format(v.normalize(), "f") if v != v.to_integral_value() else str(int(v))

    items = []
    for job, ln in rows_spec:
        evs = ev_by_job.get(job.id, [])
        item = {
            "job_id": job.id,
            "accurate_so_number": job.accurate_so_number,
            "branch_id": job.branch_id,
            "customer_name": job.customer_name,
            "so_line_id": ln.so_line_id if ln else None,
            "accurate_item_id": ln.accurate_item_id if ln else None,
            "total_buffer": _s(Decimal(ln.po_qty)) if ln else None,
            "fulfillment_qty": _s(Decimal(ln.po_qty)) if ln else None,
            "gesut_target": None,
            "done_gesut": None,
            "remaining_gesut": None,
            "ready_warehouse": None,
            "ready_state": "UNVERIFIED",
            "delivered": None,
            "delivered_state": "UNVERIFIED",
            "buffer_status": None,
            "integrity": None,
            "integrity_detail": None,
        }
        if ln is not None:
            _apply_buffer_line(item, ln, evs, asg_by_job.get(job.id, []), _s)
        items.append(item)
    return {
        "items": items[(page - 1) * page_size : page * page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
        "totals": _buffer_totals(items),
    }
