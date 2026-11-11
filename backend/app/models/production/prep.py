"""Screener & helper preparation state + append-only history."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JobLineQty(Base):
    """PO physical qty ceiling + classification per Accurate SO line."""

    __tablename__ = "job_line_qtys"
    __table_args__ = (
        UniqueConstraint("job_id", "so_line_id", name="uq_job_line_qty"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("production_jobs.id"), index=True)
    # Accurate detailItem.id — stable line identity (stringified).
    so_line_id: Mapped[str] = mapped_column(String(120))
    accurate_item_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    po_qty: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    # print | non_print | unknown — NULL means not synced; never invent print.
    production_process: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PrepState(Base):
    """Current preparation qty per job/line/role (derived from history)."""

    __tablename__ = "prep_states"
    __table_args__ = (
        UniqueConstraint("job_id", "so_line_id", "role", name="uq_prep_state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("production_jobs.id"), index=True)
    so_line_id: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16))  # screener|helper
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=0)
    evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_assignments.id"), nullable=True
    )
    updated_by: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PrepEvent(Base):
    """Append-only preparation / correction history."""

    __tablename__ = "prep_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_prep_events_idempotency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("production_jobs.id"), index=True)
    so_line_id: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16))
    event_type: Mapped[str] = mapped_column(String(32))  # set|correct
    qty_before: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    qty_after: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_assignments.id"), nullable=True
    )
    evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    actor_user_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
