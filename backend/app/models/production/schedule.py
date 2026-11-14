"""Multioperator schedule assignments with provenance."""

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


class ScheduleAssignment(Base):
    __tablename__ = "schedule_assignments"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "so_line_id",
            "color_pass",
            "operator_name",
            "machine_name",
            "work_date",
            "sequence_no",
            name="uq_schedule_assignment_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("production_jobs.id"), index=True)
    so_line_id: Mapped[str] = mapped_column(String(120))
    product_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    color_pass: Mapped[int] = mapped_column(Integer, default=1)
    operator_name: Mapped[str] = mapped_column(String(120))
    operator_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    machine_name: Mapped[str] = mapped_column(String(120))
    work_date: Mapped[date] = mapped_column(Date)
    branch_id: Mapped[str] = mapped_column(String(64))
    qty_planned: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    qty_confirmed: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=0)
    qty_cancelled_remaining: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=0)
    status: Mapped[str] = mapped_column(String(32), default="active")
    # active|cancelled_remaining|transferred|completed
    transferred_to_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_provenance: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sequence_no: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
