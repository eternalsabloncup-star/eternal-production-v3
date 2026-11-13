"""Private production attachments — POD photos/signatures (no public URLs)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

POD_PURPOSES = frozenset(
    {
        "pod_photo_1",
        "pod_photo_2",
        "pod_sig_sender",
        "pod_sig_recipient",
    }
)

# Physical Loading return evidence (not POD; not a free-text placeholder).
LOADING_RETURN_PURPOSES = frozenset({"loading_return_photo"})
UPLOAD_PURPOSES = POD_PURPOSES | LOADING_RETURN_PURPOSES


class ProductionAttachment(Base):
    __tablename__ = "production_attachments"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_production_attachments_storage_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("production_jobs.id"), index=True)
    production_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("production_events.id"), nullable=True, index=True
    )
    accurate_sj_id: Mapped[str] = mapped_column(String(120), index=True)
    purpose: Mapped[str] = mapped_column(String(32))
    storage_key: Mapped[str] = mapped_column(String(512))
    content_sha256: Mapped[str] = mapped_column(String(64))
    content_type: Mapped[str] = mapped_column(String(120))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    uploaded_by: Mapped[int] = mapped_column(Integer)
    branch_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
