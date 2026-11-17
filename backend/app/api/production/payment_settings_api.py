"""Fase 3 — production settings (PostgreSQL SoT where implemented)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, require_permissions
from app.db.session import get_db_session
from app.models.user import User
from app.services.production import branches as branch_settings
from app.services.production import payment_settings as pay_settings
from app.services.production import permissions as P
from app.services.production import operations as ops

router = APIRouter(prefix="/production/settings", tags=["production-settings"])


class PaymentApprovalSettingsBody(BaseModel):
    version: int
    payment_approval: dict
    reason: str = Field(min_length=5, max_length=500)


class BranchCreateBody(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=5, max_length=500)
    active: bool = True
    sort_order: int = 0
    accurate_branch_id: str | None = Field(default=None, max_length=64)
    address: str | None = None
    zone: str | None = Field(default=None, max_length=64)


class BranchUpdateBody(BaseModel):
    reason: str = Field(min_length=5, max_length=500)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    active: bool | None = None
    sort_order: int | None = None
    accurate_branch_id: str | None = Field(default=None, max_length=64)
    address: str | None = None
    zone: str | None = Field(default=None, max_length=64)
    # Sentinel fields: omit means leave unchanged; explicit null clears optional text.
    clear_accurate_branch_id: bool = False
    clear_address: bool = False
    clear_zone: bool = False


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
    """Master Cabang PostgreSQL + orphan efektif (job/grant)."""
    return await branch_settings.list_branches(session, user)


@router.get("/branches/audit")
async def settings_branch_audit(
    limit: int = Query(20, ge=1, le=100),
    code: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await branch_settings.list_branch_audit(session, user, limit=limit, code=code)


@router.get("/branches/{code}")
async def settings_branch_get(
    code: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(P.JOB_READ)),
):
    return await branch_settings.get_branch(session, user, code)


@router.post("/branches")
async def settings_branch_create(
    body: BranchCreateBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await branch_settings.create_branch(
        session,
        user,
        code=body.code,
        name=body.name,
        reason=body.reason,
        active=body.active,
        sort_order=body.sort_order,
        accurate_branch_id=body.accurate_branch_id,
        address=body.address,
        zone=body.zone,
    )


@router.patch("/branches/{code}")
async def settings_branch_update(
    code: str,
    body: BranchUpdateBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    kwargs: dict[str, Any] = {
        "code": code,
        "reason": body.reason,
        "name": body.name,
        "active": body.active,
        "sort_order": body.sort_order,
    }
    if body.clear_accurate_branch_id:
        kwargs["accurate_branch_id"] = None
    elif "accurate_branch_id" in body.model_fields_set:
        kwargs["accurate_branch_id"] = body.accurate_branch_id
    else:
        kwargs["accurate_branch_id"] = ...
    if body.clear_address:
        kwargs["address"] = None
    elif "address" in body.model_fields_set:
        kwargs["address"] = body.address
    else:
        kwargs["address"] = ...
    if body.clear_zone:
        kwargs["zone"] = None
    elif "zone" in body.model_fields_set:
        kwargs["zone"] = body.zone
    else:
        kwargs["zone"] = ...
    return await branch_settings.update_branch(session, user, **kwargs)


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
