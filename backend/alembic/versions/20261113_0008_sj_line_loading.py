"""P0 multi-SJ: production_events.accurate_sj_line_id.

Revision ID: 20261113_0008
Revises: 20261112_0007
Create Date: 2026-11-13

Additive / reversible. No data rewrite. No legacy backfill.
Apply only to isolated disposable test PostgreSQL unless Owner
approves staging/ops. Never run against V3 Live / production without approval.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261113_0008"
down_revision: Union[str, None] = "20261112_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "production_events",
        sa.Column("accurate_sj_line_id", sa.String(length=120), nullable=True),
    )
    op.create_index(
        "ix_production_events_loading_alloc",
        "production_events",
        [
            "job_id",
            "event_type",
            "accurate_sj_id",
            "accurate_sj_line_id",
            "so_line_id",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_production_events_loading_alloc", table_name="production_events"
    )
    op.drop_column("production_events", "accurate_sj_line_id")
