"""Baseline schema — empty metadata (no business tables yet).

Revision ID: 20261111_0001
Revises:
Create Date: 2026-11-11 00:00:00

Validated against app.db.base.Base.metadata before creation.
Future production workflow tables will add revisions on top of this head.
"""

from typing import Sequence, Union

revision: str = "20261111_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Baseline only: no ORM models / tables exist yet.
    pass


def downgrade() -> None:
    pass
