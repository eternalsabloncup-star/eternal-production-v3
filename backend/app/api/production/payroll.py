"""Operator payroll rates and period runs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.services.production import payroll as payroll_svc

router = APIRouter(prefix="/production/payroll", tags=["production-payroll"])


class RateBody(BaseModel):
    component: str
    amount: Decimal
    effective_from: date
    effective_to: date | None = None
    note: str | None = None


class RunBody(BaseModel):
    period_start: date
    period_end: date
    idempotency_key: str = Field(min_length=8, max_length=120)
    branch_id: str | None = None


@router.post("/rates")
async def create_rate(
    body: RateBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    row = await payroll_svc.set_rate(
        session,
        user,
        component=body.component,
        amount=body.amount,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
        note=body.note,
    )
    return {
        "id": row.id,
        "component": row.component,
        "amount": str(row.amount),
        "effective_from": str(row.effective_from),
        "effective_to": str(row.effective_to) if row.effective_to else None,
    }


@router.get("/rates")
async def get_rates(
    on_date: date | None = None,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    from app.services.production import permissions as P
    from app.services.production.engine import _require

    _require(user, P.PAYROLL_READ)
    rates = await payroll_svc.rates_on(session, on_date or date.today())
    return {k: str(v) for k, v in rates.items()}


@router.post("/runs")
async def create_run(
    body: RunBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    run = await payroll_svc.compute_run(
        session,
        user,
        period_start=body.period_start,
        period_end=body.period_end,
        idempotency_key=body.idempotency_key,
        branch_id=body.branch_id,
    )
    return {
        "id": run.id,
        "status": run.status,
        "period_start": str(run.period_start),
        "period_end": str(run.period_end),
        "rate_snapshot_json": run.rate_snapshot_json,
    }


@router.get("/runs/{run_id}")
async def get_run(
    run_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    run, lines = await payroll_svc.get_run(session, user, run_id)
    return {
        "id": run.id,
        "status": run.status,
        "period_start": str(run.period_start),
        "period_end": str(run.period_end),
        "rate_snapshot_json": run.rate_snapshot_json,
        "excluded_unverified_components": ["daily", "overtime"],
        "v1_parity": "unverified",
        "lines": [
            {
                "operator_name": ln.operator_name,
                "branch_id": ln.branch_id,
                "qty_one": str(ln.qty_one),
                "qty_two": str(ln.qty_two),
                "qty_three": str(ln.qty_three),
                "qty_four": str(ln.qty_four),
                "qty_screen": str(ln.qty_screen),
                "amount_gross": str(ln.amount_gross),
                "source_event_ids": ln.source_event_ids,
            }
            for ln in lines
        ],
    }
