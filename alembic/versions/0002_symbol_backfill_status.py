"""0002 add symbol_backfill_status table

Revision ID: 0002_symbol_backfill_status
Revises: 0001_daily_bars_market_data
Create Date: 2026-06-10

Tracks per-symbol backfill state so the gap-filling process knows which
symbols have already been queried and what Polygon returned.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_symbol_backfill_status"
down_revision: Union[str, None] = "0001_daily_bars_market_data"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "symbol_backfill_status",
        sa.Column("symbol_id", sa.Integer, primary_key=True),
        sa.Column("ticker", sa.Text, nullable=False),
        sa.Column("query_start_date", sa.Date, nullable=False),
        sa.Column("query_end_date", sa.Date, nullable=False),
        sa.Column("bars_returned", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("last_queried_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="market_data",
    )
    op.create_index(
        "ix_symbol_backfill_status_ticker",
        "symbol_backfill_status",
        ["ticker"],
        schema="market_data",
    )


def downgrade() -> None:
    op.drop_table("symbol_backfill_status", schema="market_data")
