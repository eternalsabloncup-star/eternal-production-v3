"""Design versions — history never deleted."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DesignVersion(Base):
    __tablename__ = "design_versions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("production_jobs.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    file_name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(512))
    uploaded_by: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    # pending|approved|rejected|superseded
    decision_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    bypass: Mapped[bool] = mapped_column(Boolean, default=False)
    customer_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
