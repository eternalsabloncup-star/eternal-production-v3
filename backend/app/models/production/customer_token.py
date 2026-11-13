"""Customer access tokens — hashed bearer links for design approval / live tracking."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CustomerAccessToken(Base):
    __tablename__ = "customer_access_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # sha256 hex of raw token — never store raw token
    scope: Mapped[str] = mapped_column(String(32), index=True)
    # design_approval | live_tracking
    job_id: Mapped[int] = mapped_column(ForeignKey("production_jobs.id"), index=True)
    design_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("design_versions.id"), nullable=True, index=True
    )
    so_line_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    customer_slug: Mapped[str] = mapped_column(String(120))
    po_slug: Mapped[str] = mapped_column(String(120))
    branch_id: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # approved | revision_requested
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
