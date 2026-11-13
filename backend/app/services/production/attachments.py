"""Private local attachment storage for Production V3 (no public URLs)."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.production.attachment import (
    LOADING_RETURN_PURPOSES,
    POD_PURPOSES,
    UPLOAD_PURPOSES,
    ProductionAttachment,
)
from app.models.production.job import ProductionJob
from app.models.user import User
from app.services.production import permissions as P
from app.services.production.engine import _branch, _require


def _require_any(user: User, *perms: str) -> None:
    have = set(user.permissions or [])
    if not (have & set(perms)):
        raise HTTPException(403, "Izin tidak mencukupi")

ALLOWED_MIME = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
    }
)
MAX_BYTES = 5 * 1024 * 1024  # 5 MiB
_SAFE_PURPOSE = re.compile(r"^[a-z0-9_]{3,32}$")


def attachment_root() -> Path:
    settings = get_settings()
    root = Path(settings.attachment_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_key(job_id: int, purpose: str, suffix: str) -> str:
    # Flat relative key under root — no user path segments.
    token = uuid.uuid4().hex
    return f"job-{job_id}/{purpose}/{token}{suffix}"


def _suffix_for_mime(content_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(content_type, ".bin")


def resolve_storage_path(storage_key: str) -> Path:
    root = attachment_root()
    # Reject absolute / traversal.
    if ".." in storage_key or storage_key.startswith("/") or "\\" in storage_key:
        raise HTTPException(400, "storage_key tidak valid")
    path = (root / storage_key).resolve()
    if not str(path).startswith(str(root)):
        raise HTTPException(400, "storage_key di luar root")
    return path


async def store_upload(
    session: AsyncSession,
    user: User,
    job: ProductionJob,
    *,
    accurate_sj_id: str,
    purpose: str,
    upload: UploadFile,
) -> ProductionAttachment:
    _branch(user, job.branch_id)
    purpose_n = (purpose or "").strip().lower()
    if purpose_n not in UPLOAD_PURPOSES or not _SAFE_PURPOSE.match(purpose_n):
        raise HTTPException(422, "purpose attachment tidak valid")
    if purpose_n in LOADING_RETURN_PURPOSES:
        # Requester may upload return evidence without full DELIVERY_MANAGE.
        _require_any(
            user,
            P.DELIVERY_LOADING_RETURN_REQUEST,
            P.DELIVERY_MANAGE,
        )
    else:
        _require(user, P.DELIVERY_MANAGE)
    sj = (accurate_sj_id or "").strip()
    if not sj:
        raise HTTPException(422, "accurate_sj_id wajib")

    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_MIME:
        raise HTTPException(422, f"MIME tidak diizinkan: {content_type or 'unknown'}")

    raw = await upload.read()
    if not raw:
        raise HTTPException(422, "File kosong")
    if len(raw) > MAX_BYTES:
        raise HTTPException(422, "File melebihi batas 5MB")

    digest = hashlib.sha256(raw).hexdigest()
    key = _safe_key(job.id, purpose_n, _suffix_for_mime(content_type))
    path = resolve_storage_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(raw)
    except OSError as exc:
        raise HTTPException(500, "Gagal menulis attachment") from exc

    row = ProductionAttachment(
        job_id=job.id,
        production_event_id=None,
        accurate_sj_id=sj,
        purpose=purpose_n,
        storage_key=key,
        content_sha256=digest,
        content_type=content_type,
        byte_size=len(raw),
        uploaded_by=user.id,
        branch_id=job.branch_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def get_attachment_for_user(
    session: AsyncSession,
    user: User,
    attachment_id: int,
) -> ProductionAttachment:
    have = set(user.permissions or [])
    if not ({P.DELIVERY_MANAGE, P.JOB_READ} & have):
        raise HTTPException(403, "Izin tidak mencukupi")
    row = await session.get(ProductionAttachment, attachment_id)
    if row is None:
        raise HTTPException(404, "Attachment tidak ditemukan")
    _branch(user, row.branch_id)
    return row


async def read_attachment_bytes(row: ProductionAttachment) -> bytes:
    path = resolve_storage_path(row.storage_key)
    if not path.is_file():
        raise HTTPException(404, "File attachment hilang")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != row.content_sha256:
        raise HTTPException(409, "Integritas attachment gagal (sha256)")
    return data


async def validate_unbound_pod_attachments(
    session: AsyncSession,
    *,
    job: ProductionJob,
    accurate_sj_id: str,
    attachment_ids: dict[str, int],
) -> dict[str, ProductionAttachment]:
    """Require exactly the four POD purposes, unbound, same job/SJ/branch."""
    sj = accurate_sj_id.strip()
    missing = [p for p in sorted(POD_PURPOSES) if p not in attachment_ids]
    if missing:
        raise HTTPException(422, f"POD attachment wajib: {', '.join(missing)}")
    out: dict[str, ProductionAttachment] = {}
    seen_ids: set[int] = set()
    for purpose in POD_PURPOSES:
        aid = int(attachment_ids[purpose])
        if aid in seen_ids:
            raise HTTPException(422, "Attachment POD harus distinct per purpose")
        seen_ids.add(aid)
        row = await session.get(ProductionAttachment, aid)
        if row is None:
            raise HTTPException(404, f"Attachment {purpose} tidak ditemukan")
        if row.job_id != job.id:
            raise HTTPException(409, f"Attachment {purpose} beda job")
        if row.branch_id != job.branch_id:
            raise HTTPException(409, f"Attachment {purpose} beda cabang")
        if row.accurate_sj_id.strip() != sj:
            raise HTTPException(409, f"Attachment {purpose} beda SJ")
        if row.purpose != purpose:
            raise HTTPException(409, f"Attachment purpose mismatch untuk {purpose}")
        if row.production_event_id is not None:
            raise HTTPException(
                409, f"Attachment {purpose} sudah terikat POD lain"
            )
        path = resolve_storage_path(row.storage_key)
        if not path.is_file():
            raise HTTPException(409, f"File attachment {purpose} hilang")
        out[purpose] = row
    return out


async def validate_unbound_loading_return_attachment(
    session: AsyncSession,
    *,
    job: ProductionJob,
    accurate_sj_id: str,
    attachment_id: int,
) -> ProductionAttachment:
    """Require a real unbound loading_return_photo for physical_return cancels."""
    sj = (accurate_sj_id or "").strip()
    if not sj:
        raise HTTPException(422, "accurate_sj_id wajib untuk bukti return")
    try:
        aid = int(attachment_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "evidence_attachment_id tidak valid") from exc
    if aid <= 0:
        raise HTTPException(422, "evidence_attachment_id tidak valid")
    row = await session.get(ProductionAttachment, aid)
    if row is None:
        raise HTTPException(404, "Attachment return tidak ditemukan")
    if row.job_id != job.id:
        raise HTTPException(409, "Attachment return beda job")
    if row.branch_id != job.branch_id:
        raise HTTPException(409, "Attachment return beda cabang")
    if row.accurate_sj_id.strip() != sj:
        raise HTTPException(409, "Attachment return beda SJ")
    if row.purpose not in LOADING_RETURN_PURPOSES:
        raise HTTPException(
            409,
            "Attachment harus purpose loading_return_photo",
        )
    if row.production_event_id is not None:
        raise HTTPException(409, "Attachment return sudah terikat event lain")
    if int(row.byte_size or 0) <= 0:
        raise HTTPException(409, "Attachment return kosong")
    path = resolve_storage_path(row.storage_key)
    if not path.is_file():
        raise HTTPException(409, "File attachment return hilang")
    # Reject zero-byte files on disk even if metadata was wrong.
    if path.stat().st_size <= 0:
        raise HTTPException(409, "File attachment return kosong")
    return row


async def bind_attachments_to_event(
    session: AsyncSession,
    attachments: dict[str, ProductionAttachment],
    event_id: int,
) -> None:
    for row in attachments.values():
        row.production_event_id = event_id
    await session.flush()


async def list_job_attachments(
    session: AsyncSession,
    job_id: int,
    *,
    accurate_sj_id: str | None = None,
) -> list[ProductionAttachment]:
    stmt = select(ProductionAttachment).where(ProductionAttachment.job_id == job_id)
    if accurate_sj_id:
        stmt = stmt.where(ProductionAttachment.accurate_sj_id == accurate_sj_id.strip())
    rows = (await session.scalars(stmt.order_by(ProductionAttachment.id))).all()
    return list(rows)
