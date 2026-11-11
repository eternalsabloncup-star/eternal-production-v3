"""SQLAlchemy declarative base and shared metadata.

No business entities or production workflow tables are defined yet.
Future models must import this Base so Alembic can discover metadata.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Typed declarative base for all V3 ORM models."""
