"""Minimal V3 work-order state for Accurate inbox processing status.

Inbox shows only Baru / Terproses derived from this table — never from
frontend stage simulation or ERP V1 import flags.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkOrder(Base):
    __tablename__ = "work_orders"
    __table_args__ = (UniqueConstraint("accurate_so_number", name="uq_work_orders_so"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    accurate_so_number: Mapped[str] = mapped_column(String(120), index=True)
    accurate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    branch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Only allowed inbox-facing values: Baru | Terproses
    processing_status: Mapped[str] = mapped_column(String(16), default="Baru")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
