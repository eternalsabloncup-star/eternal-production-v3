"""Operator payroll from confirmed production events + effective rates."""

from __future__ import annotations

from app.authorization.workflow import branch_allowed

import json
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.production.event import ProductionEvent
from app.models.production.payroll import OperatorRate, PayrollLine, PayrollRun
from app.models.production.schedule import ScheduleAssignment
from app.models.user import User
from app.services.production import permissions as P
from app.services.production.engine import _branch, _require

RATE_COMPONENTS = ("one", "two", "three", "four", "screen", "daily", "overtime")
COLOR_BUCKET = {1: "one", 2: "two", 3: "three", 4: "four"}


async def set_rate(
    session: AsyncSession,
    user: User,
    *,
    component: str,
    amount: Decimal,
    effective_from: date,
    effective_to: date | None = None,
    note: str | None = None,
) -> OperatorRate:
    _require(user, P.PAYROLL_MANAGE)
    if component not in RATE_COMPONENTS:
        raise HTTPException(422, "Komponen tarif tidak valid")
    if amount < 0:
        raise HTTPException(422, "Tarif tidak boleh negatif")
    if effective_to is not None and effective_to < effective_from:
        raise HTTPException(422, "effective_to tidak valid")
    # Close overlapping open-ended prior rate for same component.
    priors = (
        await session.scalars(
            select(OperatorRate).where(
                OperatorRate.component == component,
                OperatorRate.effective_from <= effective_from,
                or_(
                    OperatorRate.effective_to.is_(None),
                    OperatorRate.effective_to >= effective_from,
                ),
            )
        )
    ).all()
    for prior in priors:
        if prior.effective_to is None or prior.effective_to >= effective_from:
            # Snap historical end to day before new rate.
            from datetime import timedelta

            prior.effective_to = effective_from - timedelta(days=1)
            if prior.effective_to < prior.effective_from:
                prior.effective_to = prior.effective_from
    row = OperatorRate(
        component=component,
        amount=amount,
        effective_from=effective_from,
        effective_to=effective_to,
        created_by=user.id,
        note=note,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def rates_on(session: AsyncSession, on_date: date) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {c: Decimal("0") for c in RATE_COMPONENTS}
    for component in RATE_COMPONENTS:
        row = await session.scalar(
            select(OperatorRate)
            .where(
                OperatorRate.component == component,
                OperatorRate.effective_from <= on_date,
                or_(
                    OperatorRate.effective_to.is_(None),
                    OperatorRate.effective_to >= on_date,
                ),
            )
            .order_by(OperatorRate.effective_from.desc(), OperatorRate.id.desc())
            .limit(1)
        )
        if row:
            out[component] = Decimal(row.amount)
    return out


async def compute_run(
    session: AsyncSession,
    user: User,
    *,
    period_start: date,
    period_end: date,
    idempotency_key: str,
    branch_id: str | None = None,
) -> PayrollRun:
    _require(user, P.PAYROLL_MANAGE)
    if period_end < period_start:
        raise HTTPException(422, "Periode tidak valid")
    if branch_id:
        _branch(user, branch_id)

    existing = await session.scalar(
        select(PayrollRun).where(PayrollRun.idempotency_key == idempotency_key)
    )
    if existing:
        return existing

    # Snapshot rates at period_end (historical effective rates).
    # daily/overtime rates may exist but qty is NEVER invented — excluded from gross
    # until an attendance/OT timesheet source is implemented (V1 parity unverified).
    rates = await rates_on(session, period_end)
    rate_json = json.dumps(
        {
            "rates": {k: str(v) for k, v in rates.items()},
            "included_in_gross": ["one", "two", "three", "four", "screen"],
            "excluded_unverified": ["daily", "overtime"],
            "v1_parity": "unverified",
            "note": (
                "Gross uses confirmed output (+corrections −verified rejects) "
                "and linked screener units only. Attendance/OT not silently included."
            ),
        },
        sort_keys=True,
    )

    from datetime import datetime, time, timezone

    start_dt = datetime.combine(period_start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(period_end, time.max, tzinfo=timezone.utc)

    # Eligible events: confirmed + corrections; operator via assignment.
    events = (
        await session.scalars(
            select(ProductionEvent)
            .where(
                ProductionEvent.event_type.in_(
                    ["output_confirmed", "output_correction"]
                )
            )
            .order_by(ProductionEvent.id.asc())
        )
    ).all()

    rejects = (
        await session.scalars(
            select(ProductionEvent).where(
                ProductionEvent.event_type == "reject_verified"
            )
        )
    ).all()

    screen_events = (
        await session.scalars(
            select(ProductionEvent).where(ProductionEvent.event_type == "prep_screener")
        )
    ).all()

    # Index assignments across output / reject / screener prep.
    asg_ids = {e.assignment_id for e in events if e.assignment_id}
    asg_ids |= {e.assignment_id for e in rejects if e.assignment_id}
    asg_ids |= {e.assignment_id for e in screen_events if e.assignment_id}
    assignments: dict[int, ScheduleAssignment] = {}
    if asg_ids:
        rows = (
            await session.scalars(
                select(ScheduleAssignment).where(ScheduleAssignment.id.in_(asg_ids))
            )
        ).all()
        assignments = {r.id: r for r in rows}

    buckets: dict[str, dict] = {}

    def _acc(operator: str, branch: str) -> dict:
        key = operator
        if key not in buckets:
            buckets[key] = {
                "operator_name": operator,
                "branch_id": branch,
                "qty_one": Decimal("0"),
                "qty_two": Decimal("0"),
                "qty_three": Decimal("0"),
                "qty_four": Decimal("0"),
                "qty_screen": Decimal("0"),
                "event_ids": [],
            }
        return buckets[key]

    for e in events:
        if e.created_at is None:
            continue
        created = e.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created < start_dt or created > end_dt:
            continue
        if not e.assignment_id or e.assignment_id not in assignments:
            continue
        asg = assignments[e.assignment_id]
        if branch_id and asg.branch_id != branch_id:
            continue
        if not branch_allowed(user, asg.branch_id):
            continue
        b = _acc(asg.operator_name, asg.branch_id)
        bucket = COLOR_BUCKET.get(int(e.color_pass or 1), "one")
        # Work-pass qty for payroll — prefer qty_pass_ops; never treat multi-pass as stock.
        work_qty = (
            e.qty_pass_ops if e.qty_pass_ops is not None else e.qty_physical
        )
        b[f"qty_{bucket}"] = b[f"qty_{bucket}"] + Decimal(work_qty or 0)
        b["event_ids"].append(e.id)

    # Subtract verified rejects in period from same operator/color bucket.
    for e in rejects:
        if e.created_at is None:
            continue
        created = e.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created < start_dt or created > end_dt:
            continue
        if not e.assignment_id or e.assignment_id not in assignments:
            continue
        asg = assignments[e.assignment_id]
        if branch_id and asg.branch_id != branch_id:
            continue
        if not branch_allowed(user, asg.branch_id):
            continue
        b = _acc(asg.operator_name, asg.branch_id)
        bucket = COLOR_BUCKET.get(int(e.color_pass or 1), "one")
        b[f"qty_{bucket}"] = b[f"qty_{bucket}"] - Decimal(e.qty_physical or 0)
        b["event_ids"].append(e.id)

    # Intentional V3 vs V49 demo: credit screen unit to assignment operator when linked.
    for e in screen_events:
        if e.created_at is None:
            continue
        created = e.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created < start_dt or created > end_dt:
            continue
        if not e.assignment_id or e.assignment_id not in assignments:
            continue
        asg = assignments[e.assignment_id]
        if branch_id and asg.branch_id != branch_id:
            continue
        if not branch_allowed(user, asg.branch_id):
            continue
        b = _acc(asg.operator_name, asg.branch_id)
        b["qty_screen"] = b["qty_screen"] + Decimal("1")
        b["event_ids"].append(e.id)

    run = PayrollRun(
        period_start=period_start,
        period_end=period_end,
        branch_id=branch_id,
        status="finalized",
        idempotency_key=idempotency_key,
        created_by=user.id,
        rate_snapshot_json=rate_json,
    )
    session.add(run)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Payroll run idempotency conflict") from exc

    for b in buckets.values():
        for k in ("qty_one", "qty_two", "qty_three", "qty_four"):
            if b[k] < 0:
                b[k] = Decimal("0")
        gross = (
            b["qty_one"] * rates["one"]
            + b["qty_two"] * rates["two"]
            + b["qty_three"] * rates["three"]
            + b["qty_four"] * rates["four"]
            + b["qty_screen"] * rates["screen"]
        )
        session.add(
            PayrollLine(
                run_id=run.id,
                operator_name=b["operator_name"],
                branch_id=b["branch_id"],
                qty_one=b["qty_one"],
                qty_two=b["qty_two"],
                qty_three=b["qty_three"],
                qty_four=b["qty_four"],
                qty_screen=b["qty_screen"],
                amount_gross=gross.quantize(Decimal("0.01")),
                source_event_ids=json.dumps(sorted(set(b["event_ids"]))),
                rate_snapshot_json=rate_json,
            )
        )
    await session.commit()
    await session.refresh(run)
    return run


async def get_run(
    session: AsyncSession, user: User, run_id: int
) -> tuple[PayrollRun, list[PayrollLine]]:
    _require(user, P.PAYROLL_READ)
    run = await session.get(PayrollRun, run_id)
    if run is None:
        raise HTTPException(404, "Payroll run tidak ditemukan")
    if run.branch_id:
        _branch(user, run.branch_id)
    lines = (
        await session.scalars(
            select(PayrollLine)
            .where(PayrollLine.run_id == run.id)
            .order_by(PayrollLine.operator_name.asc())
        )
    ).all()
    # Filter lines to user's branches.
    lines = [ln for ln in lines if branch_allowed(user, ln.branch_id)]
    return run, list(lines)
