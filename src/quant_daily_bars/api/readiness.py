"""Readiness and health checks for the daily bars API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from quant_daily_bars._cli_impl import EXPECTED_SCHEMA_VERSION, EXPECTED_TABLES


class ReadinessError(RuntimeError):
    """Raised when the API process is live but not ready for database reads."""


@dataclass(frozen=True)
class ReadinessStatus:
    database: str
    schema_version: str
    tables: int
    latest_run: dict[str, Any] | None = None

    def as_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "ok",
            "database": self.database,
            "schema_version": self.schema_version,
            "tables": self.tables,
        }
        if self.latest_run is not None:
            result["latest_ingest_run"] = self.latest_run
        return result


def _database_url_from_env() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise ReadinessError("DATABASE_URL is not configured")
    return value


def _redact_database_url(database_url: str) -> str:
    try:
        parts = urlsplit(database_url)
    except ValueError:
        return "<redacted database url>"

    if not parts.netloc:
        return "<redacted database url>"

    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port is not None else ""
    username = parts.username or ""
    userinfo = f"{username}:***@" if username else ""
    return urlunsplit((parts.scheme, f"{userinfo}{host}{port}", parts.path, "", ""))


def sanitize_readiness_error(error: BaseException, database_url: str | None = None) -> str:
    message = str(error) or error.__class__.__name__
    if database_url:
        message = message.replace(database_url, _redact_database_url(database_url))
    return message


def check_database_readiness(database_url: str | None = None) -> ReadinessStatus:
    from sqlalchemy import create_engine, text

    resolved_url = database_url or _database_url_from_env()
    expected_table_names = tuple(sorted(EXPECTED_TABLES))
    engine = create_engine(resolved_url, pool_pre_ping=True)

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
            schema_version = connection.execute(
                text("SELECT version_num FROM market_data.alembic_version_daily_bars")
            ).scalar_one()
            tables = tuple(
                connection.execute(
                    text("""
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'market_data'
                          AND table_type = 'BASE TABLE'
                          AND table_name != 'alembic_version_daily_bars'
                        ORDER BY table_name
                    """)
                ).scalars().all()
            )

            # Latest ingest run summary
            latest_run_row = connection.execute(
                text("""
                    SELECT r.id, s.vendor_name, r.mode, r.status,
                           r.requested_start_date, r.requested_end_date,
                           r.symbols_requested, r.symbols_succeeded, r.symbols_failed,
                           r.bars_upserted, r.errors, r.duration_seconds,
                           r.started_at, r.finished_at
                    FROM market_data.vendor_bar_runs r
                    JOIN market_data.vendor_bar_sources s ON s.id = r.vendor_source_id
                    ORDER BY r.id DESC
                    LIMIT 1
                """)
            ).mappings().first()
    finally:
        engine.dispose()

    if schema_version != EXPECTED_SCHEMA_VERSION:
        raise ReadinessError(
            f"schema_version={schema_version} expected={EXPECTED_SCHEMA_VERSION}"
        )
    if tables != expected_table_names:
        raise ReadinessError(
            f"tables={','.join(tables)} expected={','.join(expected_table_names)}"
        )

    latest_run = None
    if latest_run_row is not None:
        latest_run = {
            "run_id": int(latest_run_row["id"]),
            "vendor": latest_run_row["vendor_name"],
            "mode": latest_run_row["mode"],
            "status": latest_run_row["status"],
            "from_date": str(latest_run_row["requested_start_date"]),
            "to_date": str(latest_run_row["requested_end_date"]),
            "symbols_requested": latest_run_row["symbols_requested"],
            "symbols_succeeded": latest_run_row["symbols_succeeded"],
            "symbols_failed": latest_run_row["symbols_failed"],
            "bars_upserted": latest_run_row["bars_upserted"],
            "errors": latest_run_row["errors"],
            "duration_seconds": latest_run_row["duration_seconds"],
            "started_at": latest_run_row["started_at"].isoformat() if latest_run_row["started_at"] else None,
            "finished_at": latest_run_row["finished_at"].isoformat() if latest_run_row["finished_at"] else None,
        }

    return ReadinessStatus(
        database="ok",
        schema_version=schema_version,
        tables=len(tables),
        latest_run=latest_run,
    )
