"""Master Cabang service — PostgreSQL SoT; no auto-seed; Director-only manage."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.production.branch import ProductionBranch, ProductionBranchAudit
from app.models.production.job import ProductionJob
from app.models.production.operations import ProductionMachine
from app.models.user import User
from app.services.production import permissions as P

_CODE_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def user_may_manage_branches(user: User) -> bool:
    """Stage-1: Direktur saja. Manual grant settings.branch.manage belum diizinkan."""
    from app.authorization.workflow import context

    ctx = context(user)
    if ctx is not None:
        access = getattr(ctx, "access", None)
        return bool(access is not None and getattr(access, "director", False))
    access = getattr(user, "_managed_access", None)
    if access is not None and getattr(access, "director", False):
        return True
    return P.is_payment_bypass_default_role(getattr(user, "role", None))


def _require_manage(user: User) -> None:
    if not user_may_manage_branches(user):
        raise HTTPException(403, "Hanya Direktur yang boleh mengelola Master Cabang")


def _validate_code(code: str) -> str:
    value = (code or "").strip()
    if not _CODE_RE.fullmatch(value):
        raise HTTPException(
            422,
            "Kode cabang wajib 1–64 karakter: huruf, angka, titik, underscore, atau strip",
        )
    return value


def _validate_name(name: str) -> str:
    value = (name or "").strip()
    if not value or len(value) > 120:
        raise HTTPException(422, "Nama cabang wajib 1–120 karakter")
    return value


def _row_dict(row: ProductionBranch) -> dict:
    return {
        "code": row.code,
        "name": row.name,
        "active": bool(row.active),
        "sort_order": int(row.sort_order or 0),
        "accurate_branch_id": row.accurate_branch_id,
        "address": row.address,
        "zone": row.zone,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by_user_id": row.updated_by_user_id,
        "writable": True,
        "source": "master",
    }


async def _write_audit(
    session: AsyncSession,
    *,
    actor_user_id: int,
    branch_code: str,
    action: str,
    reason: str,
    before: dict,
    after: dict,
) -> None:
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise HTTPException(422, "Alasan perubahan wajib minimal 5 karakter")
    session.add(
        ProductionBranchAudit(
            branch_code=branch_code,
            actor_user_id=actor_user_id,
            action=action,
            reason=reason[:500],
            before=before or {},
            after=after or {},
        )
    )


async def reference_counts(session: AsyncSession, code: str) -> dict[str, int]:
    jobs = await session.scalar(
        select(func.count()).select_from(ProductionJob).where(ProductionJob.branch_id == code)
    )
    machines = await session.scalar(
        select(func.count())
        .select_from(ProductionMachine)
        .where(ProductionMachine.branch_id == code)
    )
    # users.branch_ids JSONB contains code
    users = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.branch_ids.contains([code]))
    )
    # ScopedGrant.branches JSONB — table may exist
    grants = 0
    try:
        from app.authorization.models import ScopedGrant

        grants = int(
            await session.scalar(
                select(func.count())
                .select_from(ScopedGrant)
                .where(
                    ScopedGrant.active.is_(True),
                    ScopedGrant.branches.contains([code]),
                )
            )
            or 0
        )
    except Exception:
        grants = 0
    return {
        "jobs": int(jobs or 0),
        "machines": int(machines or 0),
        "users": int(users or 0),
        "grants": int(grants or 0),
    }


async def list_branches(session: AsyncSession, user: User) -> dict:
    """Master rows + orphan effective codes (jobs/grants) — orphans not writable."""
    from app.authorization.workflow import branch_allowed

    master_rows = list(
        (
            await session.scalars(
                select(ProductionBranch).order_by(
                    ProductionBranch.sort_order.asc(), ProductionBranch.code.asc()
                )
            )
        ).all()
    )
    master_codes = {r.code for r in master_rows}
    job_branches = {
        str(b)
        for b in (
            await session.scalars(select(ProductionJob.branch_id).distinct())
        ).all()
        if b
    }
    granted = {str(b) for b in (user.branch_ids or []) if b}
    can_manage = user_may_manage_branches(user)
    items = []
    for row in master_rows:
        item = _row_dict(row)
        item["writable"] = can_manage
        item["in_user_grants"] = row.code in granted
        item["seen_on_jobs"] = row.code in job_branches
        item["access_allowed"] = branch_allowed(user, row.code) if not can_manage else True
        refs = await reference_counts(session, row.code)
        item["references"] = refs
        items.append(item)
    orphans = sorted((job_branches | granted) - master_codes)
    orphan_items = [
        {
            "code": code,
            "name": code,
            "active": True,
            "sort_order": 10_000,
            "accurate_branch_id": None,
            "address": None,
            "zone": None,
            "updated_at": None,
            "updated_by_user_id": None,
            "writable": False,
            "source": "effective_orphan",
            "in_user_grants": code in granted,
            "seen_on_jobs": code in job_branches,
            "access_allowed": branch_allowed(user, code),
            "references": await reference_counts(session, code),
        }
        for code in orphans
    ]
    return {
        "items": items + orphan_items,
        "master_count": len(items),
        "orphan_count": len(orphan_items),
        "can_manage": can_manage,
        "persistence": "production_branches",
        "manual_grant_branch_manage_allowed": False,
        "note": (
            "Master Cabang PostgreSQL (production_branches). Kode immutable. "
            "Hard-delete tidak tersedia; nonaktifkan jika perlu. "
            "Tidak ada seed/auto-grant. Orphan = kode job/grant belum di master — "
            "buat master dengan kode yang sama secara eksplisit untuk mendaftarkan."
        ),
    }


async def get_branch(session: AsyncSession, user: User, code: str) -> dict:
    code = _validate_code(code)
    row = await session.get(ProductionBranch, code)
    if row is None:
        raise HTTPException(404, "Cabang master tidak ditemukan")
    body = _row_dict(row)
    body["writable"] = user_may_manage_branches(user)
    body["references"] = await reference_counts(session, code)
    return body


async def create_branch(
    session: AsyncSession,
    user: User,
    *,
    code: str,
    name: str,
    reason: str,
    active: bool = True,
    sort_order: int = 0,
    accurate_branch_id: str | None = None,
    address: str | None = None,
    zone: str | None = None,
) -> dict:
    _require_manage(user)
    code = _validate_code(code)
    name = _validate_name(name)
    existing = await session.get(ProductionBranch, code)
    if existing is not None:
        raise HTTPException(409, f"Kode cabang sudah ada: {code}")
    now = datetime.now(timezone.utc)
    row = ProductionBranch(
        code=code,
        name=name,
        active=bool(active),
        sort_order=int(sort_order or 0),
        accurate_branch_id=(accurate_branch_id or None),
        address=(address or None),
        zone=(zone or None),
        created_at=now,
        updated_at=now,
        updated_by_user_id=user.id,
    )
    session.add(row)
    await session.flush()
    after = _row_dict(row)
    await _write_audit(
        session,
        actor_user_id=user.id,
        branch_code=code,
        action="branch.create",
        reason=reason,
        before={},
        after=after,
    )
    await session.commit()
    await session.refresh(row)
    out = _row_dict(row)
    out["writable"] = True
    out["references"] = await reference_counts(session, code)
    return out


async def update_branch(
    session: AsyncSession,
    user: User,
    *,
    code: str,
    reason: str,
    name: str | None = None,
    active: bool | None = None,
    sort_order: int | None = None,
    accurate_branch_id: str | None = ...,
    address: str | None = ...,
    zone: str | None = ...,
) -> dict:
    _require_manage(user)
    code = _validate_code(code)
    row = await session.get(ProductionBranch, code)
    if row is None:
        raise HTTPException(404, "Cabang master tidak ditemukan")
    before = _row_dict(row)
    if name is not None:
        row.name = _validate_name(name)
    if active is not None:
        row.active = bool(active)
    if sort_order is not None:
        row.sort_order = int(sort_order)
    if accurate_branch_id is not ...:
        row.accurate_branch_id = accurate_branch_id or None
    if address is not ...:
        row.address = address or None
    if zone is not ...:
        row.zone = zone or None
    row.updated_by_user_id = user.id
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    after = _row_dict(row)
    action = "branch.deactivate" if before.get("active") and not after.get("active") else (
        "branch.activate" if (not before.get("active") and after.get("active")) else "branch.update"
    )
    await _write_audit(
        session,
        actor_user_id=user.id,
        branch_code=code,
        action=action,
        reason=reason,
        before=before,
        after=after,
    )
    await session.commit()
    await session.refresh(row)
    out = _row_dict(row)
    out["writable"] = True
    out["references"] = await reference_counts(session, code)
    return out


async def list_branch_audit(
    session: AsyncSession, user: User, *, limit: int = 20, code: str | None = None
) -> dict:
    if not user_may_manage_branches(user):
        raise HTTPException(403, "Audit Master Cabang hanya untuk Direktur")
    limit = min(100, max(1, int(limit)))
    q = select(ProductionBranchAudit).order_by(ProductionBranchAudit.id.desc())
    if code:
        q = q.where(ProductionBranchAudit.branch_code == _validate_code(code))
    rows = list((await session.scalars(q.limit(limit))).all())
    return {
        "items": [
            {
                "id": r.id,
                "branch_code": r.branch_code,
                "actor_user_id": r.actor_user_id,
                "action": r.action,
                "reason": r.reason,
                "before": r.before,
                "after": r.after,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }
