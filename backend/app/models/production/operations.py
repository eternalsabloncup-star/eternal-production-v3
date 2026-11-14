"""Machine master, delivery plan and append-only delivery plan history."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


class ProductionMachine(Base):
    __tablename__ = "production_machines"
    __table_args__ = (
        UniqueConstraint("branch_id", "name", name="uq_machine_branch_name"),
        CheckConstraint("kind IN ('auto','semi_auto')", name="ck_machine_kind"),
        CheckConstraint("capacity_per_shift > 0", name="ck_machine_capacity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    branch_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16), default="auto")
    capacity_per_shift: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    shifts_per_day: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DeliveryPlan(Base):
    __tablename__ = "delivery_plans"
    __table_args__ = (
        UniqueConstraint("job_id", "accurate_sj_id", name="uq_delivery_plan_sj"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("production_jobs.id"), index=True)
    accurate_sj_id: Mapped[str] = mapped_column(String(120))
    branch_id: Mapped[str] = mapped_column(String(64), index=True)
    planned_date: Mapped[date] = mapped_column(Date)
    courier_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DeliveryPlanEvent(Base):
    __tablename__ = "delivery_plan_events"
    __table_args__ = (
        UniqueConstraint("job_id", "idempotency_key", name="uq_delivery_plan_event_idem"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("delivery_plans.id"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("production_jobs.id"), index=True)
    previous_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    new_date: Mapped[date] = mapped_column(Date)
    previous_courier_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_courier_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    actor_user_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
