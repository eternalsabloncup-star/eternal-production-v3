"""Customer access tokens — mint, resolve, decide (hashed at rest).

URL shape (Owner-approved): /t/{customer_slug}/{po_slug}/{raw_token}
Authorization uses token_hash + stored scope only — never slug trust.
Bearer possession is NOT legal identity proof.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.production.customer_token import CustomerAccessToken
from app.models.production.design import DesignVersion
from app.models.production.job import ProductionJob
from app.models.user import User
from app.services.production import permissions as P
from app.services.production.engine import _branch, _require, get_job

logger = logging.getLogger("epv3.customer_tokens")

SCOPE_DESIGN_APPROVAL = "design_approval"
SCOPE_LIVE_TRACKING = "live_tracking"
VALID_SCOPES = frozenset({SCOPE_DESIGN_APPROVAL, SCOPE_LIVE_TRACKING})

DECISION_APPROVED = "approved"
DECISION_REVISION = "revision_requested"


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def slugify(value: str, *, fallback: str = "item") -> str:
    s = (value or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return (s[:100] if s else fallback)


def customer_slug_from_name(name: str | None) -> str:
    return slugify(name or "", fallback="customer")


def po_slug_from_number(po: str | None) -> str:
    return slugify(po or "", fallback="po")


def _token_prefix(token_hash: str) -> str:
    return (token_hash or "")[:8]


async def mint_customer_token(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    scope: str,
    design_version_id: int | None = None,
    so_line_id: str | None = None,
    ttl_hours: int | None = None,
) -> dict[str, Any]:
    """Mint a new token. Returns raw token ONCE — never logged."""
    _require(user, P.DESIGN_UPLOAD if scope == SCOPE_DESIGN_APPROVAL else P.TRACKING_READ)
    _branch(user, job.branch_id)
    if scope not in VALID_SCOPES:
        raise HTTPException(422, "Scope token tidak valid")

    settings = get_settings()
    if scope == SCOPE_DESIGN_APPROVAL:
        if design_version_id is None:
            raise HTTPException(422, "design_version_id wajib untuk design_approval")
        ver = await session.get(DesignVersion, design_version_id)
        if ver is None or ver.job_id != job.id:
            raise HTTPException(404, "Design version tidak ditemukan")
        if ver.status == "superseded":
            raise HTTPException(409, "Tidak dapat mint token untuk versi superseded")
        # Revoke prior active design_approval tokens for this version (replace link).
        prior = (
            await session.scalars(
                select(CustomerAccessToken).where(
                    CustomerAccessToken.job_id == job.id,
                    CustomerAccessToken.scope == SCOPE_DESIGN_APPROVAL,
                    CustomerAccessToken.design_version_id == ver.id,
                    CustomerAccessToken.revoked_at.is_(None),
                    CustomerAccessToken.decision.is_(None),
                )
            )
        ).all()
        now = datetime.now(UTC)
        for row in prior:
            row.revoked_at = now
        hours = int(
            ttl_hours
            if ttl_hours is not None
            else settings.design_approval_token_ttl_hours
        )
        line = (so_line_id or ver.so_line_id or "").strip() or None
    else:
        ver = None
        hours = int(
            ttl_hours
            if ttl_hours is not None
            else settings.live_tracking_token_ttl_hours
        )
        line = (so_line_id or "").strip() or None

    if hours < 1 or hours > 24 * 90:
        raise HTTPException(422, "TTL token di luar batas yang diizinkan")

    raw = secrets.token_urlsafe(32)  # >= 192 bits url-safe
    th = hash_token(raw)
    cslug = customer_slug_from_name(job.customer_name)
    pslug = po_slug_from_number(job.accurate_so_number)
    now = datetime.now(UTC)
    row = CustomerAccessToken(
        token_hash=th,
        scope=scope,
        job_id=job.id,
        design_version_id=ver.id if ver else None,
        so_line_id=line,
        customer_slug=cslug,
        po_slug=pslug,
        branch_id=job.branch_id,
        expires_at=now + timedelta(hours=hours),
        created_by=user.id,
        payload_json=json.dumps(
            {
                "ttl_hours": hours,
                "disclaimer": "bearer_link_is_not_legal_identity_proof",
            }
        ),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    logger.info(
        "customer_token_minted hash_prefix=%s scope=%s job_id=%s ver=%s",
        _token_prefix(th),
        scope,
        job.id,
        design_version_id,
    )
    path = f"/t/{cslug}/{pslug}/{raw}"
    base = (settings.customer_portal_public_base or "").rstrip("/")
    return {
        "id": row.id,
        "scope": scope,
        "customer_slug": cslug,
        "po_slug": pslug,
        "path": path,
        "url": f"{base}{path}" if base else path,
        "token": raw,
        "expires_at": row.expires_at.isoformat(),
        "design_version_id": design_version_id,
        "so_line_id": line,
        "ttl_hours": hours,
        "disclaimer": "Token possession is not legal identity proof.",
    }


async def revoke_design_tokens_for_job(
    session: AsyncSession,
    job_id: int,
    *,
    except_version_id: int | None = None,
) -> int:
    """Revoke open design_approval tokens (e.g. after design replacement)."""
    now = datetime.now(UTC)
    q = select(CustomerAccessToken).where(
        CustomerAccessToken.job_id == job_id,
        CustomerAccessToken.scope == SCOPE_DESIGN_APPROVAL,
        CustomerAccessToken.revoked_at.is_(None),
    )
    rows = (await session.scalars(q)).all()
    n = 0
    for row in rows:
        if except_version_id is not None and row.design_version_id == except_version_id:
            continue
        row.revoked_at = now
        n += 1
    return n


async def resolve_token(
    session: AsyncSession,
    *,
    customer_slug: str,
    po_slug: str,
    raw_token: str,
    expected_scope: str | None = None,
) -> tuple[CustomerAccessToken, ProductionJob]:
    th = hash_token(raw_token)
    row = await session.scalar(
        select(CustomerAccessToken).where(CustomerAccessToken.token_hash == th)
    )
    # Generic failures — do not leak whether hash exists.
    if row is None:
        raise HTTPException(404, "Tautan tidak valid atau sudah tidak berlaku")
    now = datetime.now(UTC)
    row.last_seen_at = now
    if row.revoked_at is not None:
        await session.commit()
        raise HTTPException(410, "Tautan sudah dicabut")
    if row.expires_at <= now:
        await session.commit()
        raise HTTPException(410, "Tautan sudah kedaluwarsa")
    if expected_scope and row.scope != expected_scope:
        await session.commit()
        raise HTTPException(403, "Scope tautan tidak sesuai")
    # Slug mismatch: reject without disclosing private data.
    if row.customer_slug != customer_slug or row.po_slug != po_slug:
        await session.commit()
        raise HTTPException(404, "Tautan tidak valid atau sudah tidak berlaku")
    job = await get_job(session, row.job_id)
    await session.commit()
    return row, job


def public_design_view(
    job: ProductionJob, ver: DesignVersion, token: CustomerAccessToken
) -> dict[str, Any]:
    """Limited payload for customer review — no payments, paths, or other customers."""
    return {
        "scope": token.scope,
        "customer_label": job.customer_name or "Pelanggan",
        "po_ref": job.accurate_so_number,
        "so_line_id": token.so_line_id or ver.so_line_id,
        "design": {
            "version_no": ver.version_no,
            "file_name": ver.file_name,
            "status": ver.status,
            "customer_approval": bool(ver.customer_approval),
        },
        "decision": token.decision,
        "expires_at": token.expires_at.isoformat() if token.expires_at else None,
        "disclaimer": (
            "Tautan ini membuktikan akses ke dokumen yang dituju, "
            "bukan identitas hukum pemegang tautan."
        ),
        "actions_allowed": token.decision is None and token.scope == SCOPE_DESIGN_APPROVAL,
    }


async def apply_design_decision(
    session: AsyncSession,
    *,
    customer_slug: str,
    po_slug: str,
    raw_token: str,
    decision: str,
    note: str | None = None,
) -> dict[str, Any]:
    if decision not in {DECISION_APPROVED, DECISION_REVISION}:
        raise HTTPException(422, "Keputusan harus approved atau revision_requested")
    th = hash_token(raw_token)
    row = await session.scalar(
        select(CustomerAccessToken).where(CustomerAccessToken.token_hash == th)
    )
    if row is None:
        raise HTTPException(404, "Tautan tidak valid atau sudah tidak berlaku")
    now = datetime.now(UTC)
    row.last_seen_at = now
    if row.customer_slug != customer_slug or row.po_slug != po_slug:
        await session.commit()
        raise HTTPException(404, "Tautan tidak valid atau sudah tidak berlaku")
    if row.scope != SCOPE_DESIGN_APPROVAL:
        await session.commit()
        raise HTTPException(403, "Scope tautan tidak sesuai untuk approval")
    if row.revoked_at is not None:
        await session.commit()
        raise HTTPException(410, "Tautan sudah dicabut")
    if row.expires_at <= now:
        await session.commit()
        raise HTTPException(410, "Tautan sudah kedaluwarsa")
    # Replay protection: already decided.
    if row.decision is not None or row.used_at is not None:
        await session.commit()
        raise HTTPException(409, "Keputusan sudah tercatat pada tautan ini")
    if row.design_version_id is None:
        await session.commit()
        raise HTTPException(409, "Token tidak terikat revisi design")
    ver = await session.get(DesignVersion, row.design_version_id)
    if ver is None or ver.job_id != row.job_id:
        await session.commit()
        raise HTTPException(404, "Revisi design tidak ditemukan")
    if ver.status == "superseded":
        row.revoked_at = now
        await session.commit()
        raise HTTPException(409, "Revisi design sudah diganti — tautan tidak berlaku")
    job = await get_job(session, row.job_id)

    row.decision = decision
    row.decision_note = (note or "").strip() or None
    row.used_at = now

    if decision == DECISION_APPROVED:
        ver.customer_approval = True
        ver.status = "approved"
        ver.decided_at = now
        job.design_status = "approved"
    else:
        ver.customer_approval = False
        ver.status = "rejected"
        ver.decision_reason = row.decision_note or "customer_revision_requested"
        ver.decided_at = now
        job.design_status = "rejected"

    await session.commit()
    logger.info(
        "customer_design_decision hash_prefix=%s decision=%s job_id=%s ver=%s",
        _token_prefix(th),
        decision,
        job.id,
        ver.id,
    )
    return {
        "ok": True,
        "decision": decision,
        "design_version_id": ver.id,
        "job_design_status": job.design_status,
        "decided_at": now.isoformat(),
    }


async def current_design_customer_approved(
    session: AsyncSession, job: ProductionJob
) -> bool:
    """True when the current non-superseded design has customer token approval."""
    if job.design_status == "bypassed":
        return True
    ver = await session.scalar(
        select(DesignVersion)
        .where(
            DesignVersion.job_id == job.id,
            DesignVersion.status.in_(["pending", "approved"]),
        )
        .order_by(DesignVersion.version_no.desc())
    )
    if ver is None:
        return False
    if ver.bypass:
        return True
    return bool(ver.customer_approval and ver.status == "approved")
