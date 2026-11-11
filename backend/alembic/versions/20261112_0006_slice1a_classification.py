"""Slice 1A: nullable Buffer/Urgent + per-line production_process + item id.

Revision ID: 20261112_0006
Revises: 20261111_0005
Create Date: 2026-11-12

Additive only. Does not invent Accurate classification defaults.
Do not apply to production without Owner approval.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_0006"
down_revision: Union[str, None] = "20261111_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "production_jobs",
        sa.Column("buffer_stock", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "production_jobs",
        sa.Column("urgent_state", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "job_line_qtys",
        sa.Column("accurate_item_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "job_line_qtys",
        sa.Column("production_process", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "job_line_qtys",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("job_line_qtys", "updated_at")
    op.drop_column("job_line_qtys", "production_process")
    op.drop_column("job_line_qtys", "accurate_item_id")
    op.drop_column("production_jobs", "urgent_state")
    op.drop_column("production_jobs", "buffer_stock")
