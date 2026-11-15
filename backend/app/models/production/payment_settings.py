"""Versioned payment-approval / bypass policy — PostgreSQL source of truth."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Fail-closed mandatory policy (cannot be disabled by settings UI).
CRITICAL_PAYMENT_SETTINGS: dict[str, bool] = {
    "partial_payment_approves": True,
    "receipt_must_be_settled": True,
    "bypass_reason_required": True,
    "bypass_audit_required": True,
    "bypass_permission_required": True,
    "recompute_on_receipt_cancel": True,
}

# Optional toggles. New installs seed bypass_enabled=false (Owner must enable).
# Existing rows keep whatever is already stored in config_json — never silently rewritten.
DEFAULT_PAYMENT_SETTINGS: dict[str, bool] = {
    **CRITICAL_PAYMENT_SETTINGS,
    "bypass_enabled": False,
    "notify_director_on_bypass": False,
}


class PaymentApprovalSettings(Base):
    __tablename__ = "payment_approval_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class PaymentApprovalSettingsAudit(Base):
    """Append-only audit for payment approval settings (not tied to a job)."""

    __tablename__ = "payment_approval_settings_audit"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    settings_version: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    actor_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    before: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    after: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
