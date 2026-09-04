"""0004 rename market_data schema to daily_bars

Revision ID: 0004_rename_schema_to_daily_bars
Revises: 0003_vendor_bar_runs_heartbeat
Create Date: 2026-09-04

Moves every table owned by this service out of the legacy ``market_data``
schema and into a dedicated ``daily_bars`` schema, then drops the now-empty
``market_data`` schema. ``ALTER TABLE ... SET SCHEMA`` is a catalog move, not a
copy, so existing rows (and each table's indexes, constraints and owned
sequences) are preserved.

The alembic version table (``alembic_version_daily_bars``) is relocated
separately in ``alembic/env.py`` before migrations run, because alembic is
actively reading and writing it while this migration executes.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004_rename_schema_to_daily_bars"
down_revision: Union[str, None] = "0003_vendor_bar_runs_heartbeat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every table owned by this service. Order does not matter: SET SCHEMA carries
# a table's indexes, constraints and owned sequences with it, and foreign keys
# between these tables are tracked by object id, not by schema-qualified name.
_TABLES = (
    "vendor_bar_sources",
    "vendor_bar_runs",
    "daily_bars",
    "corporate_actions",
    "missing_bars",
    "symbol_backfill_status",
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS daily_bars")
    for table in _TABLES:
        op.execute(f"ALTER TABLE IF EXISTS market_data.{table} SET SCHEMA daily_bars")
    # Everything this service owns has been moved out. Drop the legacy schema
    # with RESTRICT (the default) so this fails loudly rather than cascade
    # dropping anything unexpected another service may have left behind.
    op.execute("DROP SCHEMA IF EXISTS market_data RESTRICT")


def downgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS market_data")
    for table in _TABLES:
        op.execute(f"ALTER TABLE IF EXISTS daily_bars.{table} SET SCHEMA market_data")
