"""0003 vendor_bar_runs heartbeat

Revision ID: 0003_vendor_bar_runs_heartbeat
Revises: 0002_symbol_backfill_status
Create Date: 2026-07-08

Adds a heartbeat_at column to market_data.vendor_bar_runs so a background sweep
can distinguish live long-running ingestions (which update the heartbeat as they
progress, symbol by symbol) from runs whose process died mid-run and left a
stale 'running' row. Stale runs can then be safely marked 'cancelled'.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_vendor_bar_runs_heartbeat"
down_revision: Union[str, None] = "0002_symbol_backfill_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vendor_bar_runs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        schema="market_data",
    )


def downgrade() -> None:
    op.drop_column("vendor_bar_runs", "heartbeat_at", schema="market_data")
