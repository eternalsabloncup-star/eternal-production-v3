"""Canonical production job bound to one Accurate SO."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProductionJob(Base):
    __tablename__ = "production_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    accurate_so_number: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    accurate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    branch_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Gate mirrors (derived also from child tables; kept for fast queries)
    design_status: Mapped[str] = mapped_column(String(32), default="pending")
    # pending|approved|bypassed|rejected
    payment_status: Mapped[str] = mapped_column(String(32), default="pending")
    sample_status: Mapped[str] = mapped_column(String(32), default="not_required")
    # not_required|pending|approved|rejected
    processing_status: Mapped[str] = mapped_column(String(16), default="Baru")
    # Baru|Terproses
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
