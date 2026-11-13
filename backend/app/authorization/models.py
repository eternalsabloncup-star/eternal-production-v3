"""Additive access models, deliberately not registered with Alembic/runtime yet.

Import only in the isolated foundation test/package until migration parent and
cutover are approved. Existing User and production models are unchanged.
"""
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.models.user import User  # noqa: F401 - FK target

class AccessState(Base):
    __tablename__ = 'access_state'
    __table_args__ = (CheckConstraint('id = 1', name='ck_access_state_singleton'), CheckConstraint('revision >= 0', name='ck_access_revision_positive'))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    bootstrapped: Mapped[bool] = mapped_column(Boolean, default=False)

class AccessGroup(Base):
    __tablename__ = 'access_groups'
    __table_args__ = (CheckConstraint("system_key IS NULL OR system_key = 'director'", name='ck_access_group_system'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    system_key: Mapped[str | None] = mapped_column(String(32), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Membership(Base):
    __tablename__ = 'access_memberships'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('access_groups.id', ondelete='RESTRICT'), primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class ScopedGrant(Base):
    __tablename__ = 'access_grants'
    __table_args__ = (
        UniqueConstraint('group_id', 'capability', 'branches', 'ownership', 'assignments', name='uq_access_grant_scope'),
        CheckConstraint("ownership IN ('all', 'own', 'selected')", name='ck_access_grant_ownership'),
        CheckConstraint("jsonb_typeof(branches) = 'array' AND jsonb_typeof(assignments) = 'array'", name='ck_access_grant_arrays'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('access_groups.id', ondelete='RESTRICT'), index=True)
    capability: Mapped[str] = mapped_column(String(120))
    branches: Mapped[list] = mapped_column(JSONB, default=list)
    ownership: Mapped[str] = mapped_column(String(16), default='all')
    assignments: Mapped[list] = mapped_column(JSONB, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class AccessAudit(Base):
    __tablename__ = 'access_audit'
    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, unique=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    action: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(String(500))
    before: Mapped[dict] = mapped_column(JSONB)
    after: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

TABLES = [User.__table__, AccessState.__table__, AccessGroup.__table__, Membership.__table__, ScopedGrant.__table__, AccessAudit.__table__]
