"""Operator rates (effective-dated) and payroll runs from confirmed output."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
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


class OperatorRate(Base):
    """Effective-dated rate components. Historical rows are retained."""

    __tablename__ = "operator_rates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(String(32), index=True)
    # one|two|three|four|screen|daily|overtime
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PayrollRun(Base):
    __tablename__ = "payroll_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_payroll_runs_idempotency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    branch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="finalized")
    idempotency_key: Mapped[str] = mapped_column(String(120))
    created_by: Mapped[int] = mapped_column(Integer)
    rate_snapshot_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PayrollLine(Base):
    __tablename__ = "payroll_lines"
    __table_args__ = (
        UniqueConstraint("run_id", "operator_name", name="uq_payroll_line_operator"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.id"), index=True)
    operator_name: Mapped[str] = mapped_column(String(120))
    branch_id: Mapped[str] = mapped_column(String(64))
    qty_one: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=0)
    qty_two: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=0)
    qty_three: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=0)
    qty_four: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=0)
    qty_screen: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=0)
    amount_gross: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    source_event_ids: Mapped[str] = mapped_column(Text)  # json list
    rate_snapshot_json: Mapped[str] = mapped_column(Text)
