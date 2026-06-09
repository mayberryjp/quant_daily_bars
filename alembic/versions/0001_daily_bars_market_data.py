"""0001 daily bars and market data schema

Revision ID: 0001_daily_bars_market_data
Revises:
Create Date: 2026-06-09

Creates the market_data schema with tables for:
- vendor_bar_sources: registered bar data vendors
- vendor_bar_runs: per-run tracking for bar ingestion jobs
- daily_bars: OHLCV bars keyed by (symbol_id, bar_date, adjustment_type)
- corporate_actions: splits, dividends, symbol changes
- missing_bars: tracking for bars that were expected but not returned
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_daily_bars_market_data"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS market_data")

    # ── vendor_bar_sources ──────────────────────────────────────────
    op.create_table(
        "vendor_bar_sources",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("vendor_name", sa.Text, nullable=False, unique=True),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="market_data",
    )
    op.execute(
        "INSERT INTO market_data.vendor_bar_sources (vendor_name, description) "
        "VALUES ('polygon', 'Polygon.io aggregates/bars API')"
    )

    # ── vendor_bar_runs ─────────────────────────────────────────────
    op.create_table(
        "vendor_bar_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("vendor_source_id", sa.Integer, sa.ForeignKey("market_data.vendor_bar_sources.id"), nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'running'")),
        sa.Column("mode", sa.Text, nullable=False),  # 'backfill' or 'incremental'
        sa.Column("requested_start_date", sa.Date, nullable=False),
        sa.Column("requested_end_date", sa.Date, nullable=False),
        sa.Column("symbols_requested", sa.Integer, server_default=sa.text("0")),
        sa.Column("symbols_succeeded", sa.Integer, server_default=sa.text("0")),
        sa.Column("symbols_failed", sa.Integer, server_default=sa.text("0")),
        sa.Column("bars_upserted", sa.Integer, server_default=sa.text("0")),
        sa.Column("errors", sa.Integer, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text),
        sa.Column("duration_seconds", sa.Float),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        schema="market_data",
    )

    # ── daily_bars ──────────────────────────────────────────────────
    # symbol_id references the quant_symbols symbol_master.symbols table.
    # When databases are separate, this is a logical FK enforced at application level.
    # adjustment_type: 'unadjusted' stores raw exchange prices,
    #                  'split_adjusted' stores prices adjusted for splits only.
    # Both are stored so downstream consumers can choose the series they need.
    op.create_table(
        "daily_bars",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol_id", sa.Integer, nullable=False),
        sa.Column("ticker", sa.Text, nullable=False),
        sa.Column("bar_date", sa.Date, nullable=False),
        sa.Column("adjustment_type", sa.Text, nullable=False, server_default=sa.text("'unadjusted'")),
        sa.Column("open", sa.Numeric(18, 6), nullable=False),
        sa.Column("high", sa.Numeric(18, 6), nullable=False),
        sa.Column("low", sa.Numeric(18, 6), nullable=False),
        sa.Column("close", sa.Numeric(18, 6), nullable=False),
        sa.Column("volume", sa.BigInteger, nullable=False),
        sa.Column("vwap", sa.Numeric(18, 6)),
        sa.Column("transactions", sa.Integer),
        sa.Column("vendor_source_id", sa.Integer, sa.ForeignKey("market_data.vendor_bar_sources.id"), nullable=False),
        sa.Column("vendor_bar_run_id", sa.BigInteger, sa.ForeignKey("market_data.vendor_bar_runs.id")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="market_data",
    )
    # Unique constraint enforces idempotent upserts
    op.create_unique_constraint(
        "uq_daily_bars_symbol_date_adj",
        "daily_bars",
        ["symbol_id", "bar_date", "adjustment_type"],
        schema="market_data",
    )
    op.create_index("ix_daily_bars_ticker_date", "daily_bars", ["ticker", "bar_date"], schema="market_data")
    op.create_index("ix_daily_bars_bar_date", "daily_bars", ["bar_date"], schema="market_data")
    op.create_index("ix_daily_bars_run_id", "daily_bars", ["vendor_bar_run_id"], schema="market_data")

    # ── corporate_actions ───────────────────────────────────────────
    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol_id", sa.Integer, nullable=False),
        sa.Column("ticker", sa.Text, nullable=False),
        sa.Column("action_type", sa.Text, nullable=False),  # 'split', 'dividend', 'symbol_change'
        sa.Column("ex_date", sa.Date, nullable=False),
        sa.Column("record_date", sa.Date),
        sa.Column("payment_date", sa.Date),
        # For splits: split_from / split_to (e.g. 1:4 means split_from=1, split_to=4)
        sa.Column("split_from", sa.Numeric(18, 6)),
        sa.Column("split_to", sa.Numeric(18, 6)),
        # For dividends: cash_amount and currency
        sa.Column("cash_amount", sa.Numeric(18, 6)),
        sa.Column("currency", sa.Text),
        # For symbol changes: old_ticker / new_ticker
        sa.Column("old_ticker", sa.Text),
        sa.Column("new_ticker", sa.Text),
        sa.Column("vendor_source_id", sa.Integer, sa.ForeignKey("market_data.vendor_bar_sources.id")),
        sa.Column("raw_payload", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="market_data",
    )
    op.create_index("ix_corporate_actions_symbol_date", "corporate_actions", ["symbol_id", "ex_date"], schema="market_data")
    op.create_index("ix_corporate_actions_type", "corporate_actions", ["action_type"], schema="market_data")

    # ── missing_bars ────────────────────────────────────────────────
    # Tracks symbols/dates where bars were expected but not returned by the vendor.
    op.create_table(
        "missing_bars",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol_id", sa.Integer, nullable=False),
        sa.Column("ticker", sa.Text, nullable=False),
        sa.Column("bar_date", sa.Date, nullable=False),
        sa.Column("vendor_source_id", sa.Integer, sa.ForeignKey("market_data.vendor_bar_sources.id"), nullable=False),
        sa.Column("vendor_bar_run_id", sa.BigInteger, sa.ForeignKey("market_data.vendor_bar_runs.id")),
        sa.Column("reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="market_data",
    )
    op.create_unique_constraint(
        "uq_missing_bars_symbol_date_vendor",
        "missing_bars",
        ["symbol_id", "bar_date", "vendor_source_id"],
        schema="market_data",
    )


def downgrade() -> None:
    op.drop_table("missing_bars", schema="market_data")
    op.drop_table("corporate_actions", schema="market_data")
    op.drop_table("daily_bars", schema="market_data")
    op.drop_table("vendor_bar_runs", schema="market_data")
    op.drop_table("vendor_bar_sources", schema="market_data")
    op.execute("DROP SCHEMA IF EXISTS market_data CASCADE")
