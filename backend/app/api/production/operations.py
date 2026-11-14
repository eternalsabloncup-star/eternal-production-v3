"""Delivery schedule, machine master, production report and assignee endpoints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, require_permissions
from app.db.session import get_db_session
from app.api.production_inbox import get_gateway
from app.models.user import User
from app.services.accurate_read_gateway import ReadGateway
from app.services.production import operations as ops, permissions as P

router = APIRouter(prefix="/production/ops", tags=["production-operations"])


class DeliveryPlanBody(BaseModel):
    accurate_sj_id: str
    planned_date: date
    courier_user_id: int | None = None
    reason: str | None = None
    idempotency_key: str


class DriftAckBody(BaseModel):
    so_line_id: str
    reason: str
    idempotency_key: str


class MachineBody(BaseModel):
    branch_id: str
    name: str
    kind: str = "auto"
    capacity_per_shift: Decimal | None = None
    shifts_per_day: int = 1


class MachinePatchBody(BaseModel):
    kind: str | None = None
    capacity_per_shift: Decimal | None = None
    shifts_per_day: int | None = None
    active: bool | None = None


@router.get("/deliveries")
async def deliveries_list(
    q: str | None = None,
    status: str | None = Query(
        None,
        pattern="^(belum_dijadwalkan|terjadwal|hari_ini|terlambat|terkirim|sebagian|belum_dikirim|dibatalkan)$",
    ),
    branch: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    return await ops.list_deliveries(
        session, user, q=q, status=status, branch=branch, date_from=date_from,
        date_to=date_to, page=page, page_size=page_size,
    )


@router.get("/buffer")
async def buffer_monitor(
    q: str | None = None,
    branch: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    return await ops.list_buffer_monitor(session, user, q=q, branch=branch, page=page, page_size=page_size)


@router.post("/jobs/{job_id}/delivery-plan")
async def delivery_plan_save(
    job_id: int,
    body: DeliveryPlanBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await ops.plan_delivery(
        session, user, job_id, accurate_sj_id=body.accurate_sj_id, planned_date=body.planned_date,
        courier_user_id=body.courier_user_id, reason=body.reason, idempotency_key=body.idempotency_key,
    )


@router.get("/machines")
async def machines_list(
    branch: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    return await ops.list_machines(session, user, branch=branch)


@router.post("/machines")
async def machine_create(
    body: MachineBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await ops.create_machine(
        session, user, branch_id=body.branch_id, name=body.name, kind=body.kind,
        capacity_per_shift=body.capacity_per_shift, shifts_per_day=body.shifts_per_day,
    )


@router.patch("/machines/{machine_id}")
async def machine_update(
    machine_id: int,
    body: MachinePatchBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await ops.update_machine(
        session, user, machine_id, capacity_per_shift=body.capacity_per_shift,
        shifts_per_day=body.shifts_per_day, active=body.active, kind=body.kind,
    )


@router.get("/reports/summary")
async def report_summary(
    branch: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    return await ops.production_report(session, user, branch=branch, date_from=date_from, date_to=date_to)


@router.get("/assignees")
async def assignees_list(
    branch: str,
    kind: str = Query("operator", pattern="^(operator|courier)$"),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    return await ops.list_assignees(session, user, kind=kind, branch=branch)


@router.get("/jobs/{job_id}/delivery-plan-history")
async def delivery_plan_history(
    job_id: int,
    accurate_sj_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    return {"items": await ops.list_plan_history(session, user, job_id, accurate_sj_id)}


@router.get("/payment/unsynced")
async def payment_unsynced_list(
    page: int = Query(1, ge=1, le=100000),
    limit: int = Query(50, ge=1, le=100),
    keyword: str = Query("", max_length=120),
    gateway: ReadGateway = Depends(get_gateway),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    return await ops.list_unsynced_payment_pos(
        session, user, gateway, page=page, limit=limit, keyword=keyword
    )


@router.post("/jobs/{job_id}/qty-drift/acknowledge")
async def drift_acknowledge(
    job_id: int,
    body: DriftAckBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await ops.acknowledge_qty_drift(
        session, user, job_id, so_line_id=body.so_line_id, reason=body.reason,
        idempotency_key=body.idempotency_key,
    )


@router.get("/payroll/runs")
async def payroll_runs_list(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await ops.list_payroll_runs(session, user)
