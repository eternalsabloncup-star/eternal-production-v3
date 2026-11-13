"""Append-only production events (output, reject, packing, delivery, audit)."""

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


class ProductionEvent(Base):
    """Immutable ledger. Corrections are new compensating events."""

    __tablename__ = "production_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_production_events_idempotency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("production_jobs.id"), index=True)
    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_assignments.id"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    # output_confirmed|output_correction|reject|reject_verified|
    # packing_batch|loading|pod|sj_ref|sj_cancelled|wip_hold|note
    so_line_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    color_pass: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lot_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    qty_physical: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    qty_pass_ops: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    # print-pass operations may exceed physical cups for multicolor
    accurate_sj_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    accurate_sj_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    actor_user_id: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
