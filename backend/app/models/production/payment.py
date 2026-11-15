"""Accurate payment receipt references and gate state."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Index,
    Numeric,
    String,
    Text,
    text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaymentReceiptRef(Base):
    __tablename__ = "payment_receipt_refs"
    __table_args__ = (
        Index("uq_payment_receipt_active", "accurate_receipt_id", unique=True,
              postgresql_where=text("status = 'valid'")),
        Index("uq_payment_receipt_request", "job_id", "idempotency_key", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("production_jobs.id"), index=True)
    accurate_receipt_id: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    accurate_receipt_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Accurate sales-receipt paid/trans date when provided by gateway; never invented.
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(32), default="valid")
    # valid|invalidated|reversed
    recorded_by: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PaymentBypass(Base):
    __tablename__ = "payment_bypasses"
    __table_args__ = (
        Index(
            "uq_payment_bypass_request",
            "job_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("production_jobs.id"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    authorized_by: Mapped[int] = mapped_column(Integer)
    # Optional retry key — duplicate requests with the same key replay, not re-authorize.
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Production-payment gate at authorization time (approved|bypassed|pending).
    gate_before: Mapped[str | None] = mapped_column(String(32), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    revoked_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
