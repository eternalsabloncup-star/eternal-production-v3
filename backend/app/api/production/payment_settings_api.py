"""Fase 3 — production settings (PostgreSQL SoT where implemented)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, require_permissions
from app.db.session import get_db_session
from app.models.production.job import ProductionJob
from app.models.user import User
from app.services.production import payment_settings as pay_settings
from app.services.production import permissions as P
from app.services.production import operations as ops

router = APIRouter(prefix="/production/settings", tags=["production-settings"])


class PaymentApprovalSettingsBody(BaseModel):
    version: int
    payment_approval: dict
    reason: str = Field(min_length=5, max_length=500)


@router.get("/payment-approval")
async def payment_approval_settings_get(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """PostgreSQL-backed payment approval / bypass policy."""
    return await pay_settings.read_payment_approval(session, user)


@router.put("/payment-approval")
async def payment_approval_settings_put(
    body: PaymentApprovalSettingsBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await pay_settings.update_payment_approval(
        session,
        user,
        version=body.version,
        payment_approval=body.payment_approval,
        reason=body.reason,
    )


@router.get("/payment-approval/audit")
async def payment_approval_settings_audit(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await pay_settings.list_payment_approval_audit(session, user, limit=limit)


@router.get("/branches")
async def settings_branches_effective(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    """Cabang efektif (read-only) — bukan master sandbox editable.

    Sumber: user.branch_ids + cabang yang muncul pada ProductionJob.
    Master cabang writable (CRUD seperti sandbox) memerlukan keputusan Direktur
    (skema baru) dan tidak dipalsukan di sini.
    """
    from app.authorization.workflow import branch_allowed

    job_branches = list(
        (await session.scalars(select(ProductionJob.branch_id).distinct())).all()
    )
    granted = list(user.branch_ids or [])
    codes = sorted({*(str(b) for b in job_branches if b), *(str(b) for b in granted if b)})
    items = [
        {
            "code": code,
            "name": code,
            "active": branch_allowed(user, code),
            "in_user_grants": code in granted,
            "seen_on_jobs": code in {str(b) for b in job_branches if b},
            "writable": False,
        }
        for code in codes
    ]
    return {
        "items": items,
        "can_manage": False,
        "persistence": None,
        "note": (
            "Hanya baca. Master Cabang editable (SIMPAN→AUDIT) belum diotorisasi sebagai "
            "skema PostgreSQL baru — sandbox SQLite bukan SoT Live. "
            "Gunakan akses user + data Accurate/job."
        ),
    }


@router.get("/machines-summary")
async def settings_machines_summary(
    branch: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    """Ringkasan Master Mesin (PostgreSQL) — CRUD penuh di /production/ops/machines."""
    body = await ops.list_machines(session, user, branch=branch)
    return {
        **body,
        "can_manage": True,
        "persistence": "production_machines",
        "mutate_via": "/api/v1/production/ops/machines",
        "note": "Master Mesin sudah PostgreSQL; ubah lewat halaman Master Mesin / API ops.",
    }
