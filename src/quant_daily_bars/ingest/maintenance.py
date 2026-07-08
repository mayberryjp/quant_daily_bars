"""Maintenance helpers for bar ingestion bookkeeping."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

DEFAULT_STALE_AFTER_MINUTES = 30
STALE_REASON = "cancelled by stale-run sweep: no heartbeat"

_CANCEL_STALE_RUNS = text("""
    UPDATE market_data.vendor_bar_runs
    SET status = 'cancelled',
        finished_at = now(),
        duration_seconds = COALESCE(
            duration_seconds,
            EXTRACT(EPOCH FROM (now() - started_at))
        ),
        error_message = COALESCE(error_message, :reason)
    WHERE status = 'running'
      AND finished_at IS NULL
      AND COALESCE(heartbeat_at, started_at) < now() - make_interval(mins => :minutes)
    RETURNING id
""")


def cancel_stale_runs(
    engine: Engine,
    stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES,
    reason: str = STALE_REASON,
) -> list[int]:
    """Mark orphaned 'running' vendor_bar_runs as 'cancelled'.

    A run is considered stale when it is still ``running`` but its last heartbeat
    (or its start time, if it never heartbeated) is older than
    ``stale_after_minutes``. Live runs update ``heartbeat_at`` as they progress,
    so a long but healthy backfill is never cancelled. Returns the list of run
    ids that were cancelled.
    """
    with engine.begin() as conn:
        rows = conn.execute(
            _CANCEL_STALE_RUNS,
            {"minutes": stale_after_minutes, "reason": reason},
        ).fetchall()
    return [row[0] for row in rows]
