"""Payment approval settings — PostgreSQL SoT, fail-closed critical keys."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.production.payment_settings import (
    CRITICAL_PAYMENT_SETTINGS,
    DEFAULT_PAYMENT_SETTINGS,
    PaymentApprovalSettings,
    PaymentApprovalSettingsAudit,
)
from app.models.user import User
from app.services.production import permissions as P


def _merged(config: dict | None) -> dict[str, bool]:
    out = dict(DEFAULT_PAYMENT_SETTINGS)
    if isinstance(config, dict):
        for key, value in config.items():
            if key in out and isinstance(value, bool):
                out[key] = value
    # Critical keys always win.
    out.update(CRITICAL_PAYMENT_SETTINGS)
    return out


def validate_approval_settings(cfg: dict) -> dict[str, bool]:
    if not isinstance(cfg, dict):
        raise HTTPException(422, "payment_approval wajib objek")
    # Reject explicit attempts to weaken critical keys before merge.
    for key, required in CRITICAL_PAYMENT_SETTINGS.items():
        if key in cfg and cfg[key] is not required:
            raise HTTPException(
                422,
                f"Pengaturan kritis {key} wajib {required} dan tidak boleh dilemahkan",
            )
    merged = _merged(cfg)
    for key, required in CRITICAL_PAYMENT_SETTINGS.items():
        if merged.get(key) is not required:
            raise HTTPException(
                422,
                f"Pengaturan kritis {key} wajib {required} dan tidak boleh dilemahkan",
            )
    return merged


async def get_or_create_settings(session: AsyncSession) -> PaymentApprovalSettings:
    row = await session.scalar(
        select(PaymentApprovalSettings).order_by(PaymentApprovalSettings.id.asc()).limit(1)
    )
    if row is not None:
        return row
    row = PaymentApprovalSettings(version=1, config_json=dict(DEFAULT_PAYMENT_SETTINGS))
    session.add(row)
    await session.flush()
    return row


def user_may_manage_payment_settings(user: User) -> bool:
    """Direktur (legacy role / enforced system director) or explicit settings grant."""
    from app.authorization.workflow import context

    ctx = context(user)
    if ctx is not None:
        access = getattr(ctx, "access", None)
        if access is not None and getattr(access, "director", False):
            return True
        return bool(getattr(ctx, "can", lambda _c: False)("settings.grant.manage"))
    access = getattr(user, "_managed_access", None)
    if access is not None and getattr(access, "director", False):
        return True
    perms = set(user.permissions or [])
    if "settings.payment_approval.manage" in perms or "production.settings.payment_approval" in perms:
        return True
    return P.is_payment_bypass_default_role(getattr(user, "role", None))


async def read_payment_approval(session: AsyncSession, user: User) -> dict:
    row = await get_or_create_settings(session)
    await session.commit()
    cfg = _merged(row.config_json)
    return {
        "version": row.version,
        "can_manage": user_may_manage_payment_settings(user),
        "payment_approval": cfg,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by_user_id": row.updated_by_user_id,
        "critical_locked": sorted(CRITICAL_PAYMENT_SETTINGS),
        "note": (
            "Pengaturan tersimpan di PostgreSQL V3. Kunci kritis tidak dapat dimatikan. "
            "Invoice/outstanding Accurate tetap UNKNOWN hingga kontrak alokasi disetujui. "
            "Instalasi baru: bypass_enabled=false sampai Owner mengaktifkan di sini. "
            "Baris yang sudah tersimpan tidak diubah diam-diam. "
            "Permission Direktur/grant tetap wajib; bypass tidak mengubah Accurate."
        ),
    }


async def list_payment_approval_audit(
    session: AsyncSession,
    user: User,
    *,
    limit: int = 20,
) -> dict:
    _ = user
    limit = min(100, max(1, int(limit)))
    rows = (
        await session.scalars(
            select(PaymentApprovalSettingsAudit)
            .order_by(PaymentApprovalSettingsAudit.id.desc())
            .limit(limit)
        )
    ).all()
    return {
        "items": [
            {
                "id": r.id,
                "settings_version": r.settings_version,
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


async def update_payment_approval(
    session: AsyncSession,
    user: User,
    *,
    version: int,
    payment_approval: dict,
    reason: str,
) -> dict:
    if not user_may_manage_payment_settings(user):
        raise HTTPException(403, "Izin mengelola pengaturan approval payment tidak mencukupi")
    reason_s = (reason or "").strip()
    if len(reason_s) < 5:
        raise HTTPException(422, "Alasan perubahan pengaturan wajib")
    if len(reason_s) > 500:
        raise HTTPException(422, "Alasan terlalu panjang")
    if not isinstance(version, int) or version < 1:
        raise HTTPException(422, "version wajib")
    validated = validate_approval_settings(payment_approval or {})
    row = await get_or_create_settings(session)
    if row.version != version:
        raise HTTPException(409, "Versi pengaturan kedaluwarsa — muat ulang lalu simpan lagi")
    before = _merged(row.config_json)
    row.config_json = validated
    row.version = row.version + 1
    row.updated_by_user_id = user.id
    row.note = reason_s
    await session.flush()
    session.add(
        PaymentApprovalSettingsAudit(
            settings_version=row.version,
            actor_user_id=user.id,
            action="payment_approval.settings.update",
            reason=reason_s,
            before=before,
            after=validated,
        )
    )
    await session.commit()
    return await read_payment_approval(session, user)


async def bypass_enabled(session: AsyncSession) -> bool:
    """Effective bypass toggle.

    - No settings row yet → False (instalasi baru / belum dikonfigurasi).
    - Existing row → stored value (never silently rewritten).
    First Settings GET/PUT seeds DEFAULT with bypass_enabled=false.
    """
    row = await session.scalar(
        select(PaymentApprovalSettings).order_by(PaymentApprovalSettings.id.asc()).limit(1)
    )
    if row is None:
        return False
    return bool(_merged(row.config_json).get("bypass_enabled", False))
