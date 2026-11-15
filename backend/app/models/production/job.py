"""Canonical production job bound to one Accurate SO."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Explicit lifecycle machine — never free-form status strings.
LIFECYCLE_ACTIVE = "active"
LIFECYCLE_CANCELLED = "cancelled"
LIFECYCLE_STATUSES = frozenset({LIFECYCLE_ACTIVE, LIFECYCLE_CANCELLED})


class ProductionJob(Base):
    __tablename__ = "production_jobs"
    __table_args__ = (
        CheckConstraint(
            "lifecycle_status IN ('active', 'cancelled')",
            name="ck_production_jobs_lifecycle_status",
        ),
        # Multiple cancelled historical jobs may share an SO number.
        # At most one active job per canonical Accurate SO identity.
        Index(
            "uq_production_jobs_active_so",
            "accurate_so_number",
            unique=True,
            postgresql_where=text("lifecycle_status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    accurate_so_number: Mapped[str] = mapped_column(String(120), index=True)
    accurate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    branch_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Order-level Buffer / Non-Buffer — NULL = unknown (never invent false).
    buffer_stock: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    # Urgent workflow room: NULL unknown | normal | pending_request |
    # approved_urgent | legacy_urgent (V1-aligned labels; no auto Accurate map).
    urgent_state: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    # Gate mirrors (derived also from child tables; kept for fast queries)
    design_status: Mapped[str] = mapped_column(String(32), default="pending")
    # pending|approved|bypassed|rejected
    payment_status: Mapped[str] = mapped_column(String(32), default="pending")
    sample_status: Mapped[str] = mapped_column(String(32), default="not_required")
    # not_required|pending|approved|rejected
    processing_status: Mapped[str] = mapped_column(String(16), default="Baru")
    # Baru|Terproses
    # Soft cancel lifecycle (Fase 1C). Cancelled jobs stay in history.
    lifecycle_status: Mapped[str] = mapped_column(
        String(16), default=LIFECYCLE_ACTIVE, server_default=LIFECYCLE_ACTIVE, index=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_gate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # safe_auto | requires_review | blocked (decision recorded at cancel time)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
