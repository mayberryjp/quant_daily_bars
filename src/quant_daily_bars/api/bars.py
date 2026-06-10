"""Daily bars data access for the API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BarListParams:
    ticker: str | None = None
    symbol_id: int | None = None
    from_date: str | None = None
    to_date: str | None = None
    adjustment_type: str | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True)
class IngestRunListParams:
    status: str | None = None
    mode: str | None = None
    limit: int = 20
    offset: int = 0


def _engine():
    from sqlalchemy import create_engine
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return create_engine(database_url, pool_pre_ping=True)


def list_bars(params: BarListParams) -> dict[str, Any]:
    from sqlalchemy import text

    engine = _engine()
    try:
        with engine.connect() as conn:
            where_parts = []
            values: dict[str, Any] = {"limit": params.limit, "offset": params.offset}

            if params.ticker is not None:
                where_parts.append("d.ticker = :ticker")
                values["ticker"] = params.ticker
            if params.symbol_id is not None:
                where_parts.append("d.symbol_id = :symbol_id")
                values["symbol_id"] = params.symbol_id
            if params.from_date is not None:
                where_parts.append("d.bar_date >= :from_date")
                values["from_date"] = params.from_date
            if params.to_date is not None:
                where_parts.append("d.bar_date <= :to_date")
                values["to_date"] = params.to_date
            if params.adjustment_type is not None:
                where_parts.append("d.adjustment_type = :adjustment_type")
                values["adjustment_type"] = params.adjustment_type

            where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

            rows = conn.execute(
                text(f"""
                    SELECT d.id, d.symbol_id, d.ticker, d.bar_date,
                           d.adjustment_type, d.open, d.high, d.low, d.close,
                           d.volume, d.vwap, d.transactions,
                           d.fetched_at, d.vendor_bar_run_id
                    FROM market_data.daily_bars d
                    {where_clause}
                    ORDER BY d.bar_date ASC, d.ticker ASC
                    LIMIT :limit OFFSET :offset
                """),
                values,
            ).mappings().all()
    finally:
        engine.dispose()

    items = [_bar_to_item(row) for row in rows]
    return {
        "items": items,
        "limit": params.limit,
        "offset": params.offset,
        "count": len(items),
    }


def get_bar_summary(ticker: str) -> dict[str, Any] | None:
    from sqlalchemy import text

    engine = _engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT d.ticker, d.symbol_id,
                           MIN(d.bar_date) AS first_date,
                           MAX(d.bar_date) AS last_date,
                           COUNT(*) AS bar_count,
                           d.adjustment_type
                    FROM market_data.daily_bars d
                    WHERE d.ticker = :ticker
                    GROUP BY d.ticker, d.symbol_id, d.adjustment_type
                """),
                {"ticker": ticker},
            ).mappings().first()
    finally:
        engine.dispose()

    if row is None:
        return None

    return {
        "ticker": row["ticker"],
        "symbol_id": int(row["symbol_id"]),
        "first_date": str(row["first_date"]),
        "last_date": str(row["last_date"]),
        "bar_count": int(row["bar_count"]),
        "adjustment_type": row["adjustment_type"],
    }


def list_tickers_coverage() -> dict[str, Any]:
    from sqlalchemy import text

    engine = _engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT d.ticker, d.symbol_id,
                           MIN(d.bar_date) AS first_date,
                           MAX(d.bar_date) AS last_date,
                           COUNT(*) AS bar_count
                    FROM market_data.daily_bars d
                    GROUP BY d.ticker, d.symbol_id
                    ORDER BY d.ticker
                """)
            ).mappings().all()
    finally:
        engine.dispose()

    items = [
        {
            "ticker": row["ticker"],
            "symbol_id": int(row["symbol_id"]),
            "first_date": str(row["first_date"]),
            "last_date": str(row["last_date"]),
            "bar_count": int(row["bar_count"]),
        }
        for row in rows
    ]
    return {"items": items, "count": len(items)}


def list_ingest_runs(params: IngestRunListParams) -> dict[str, Any]:
    from sqlalchemy import text

    engine = _engine()
    try:
        with engine.connect() as conn:
            where_parts = []
            values: dict[str, Any] = {"limit": params.limit, "offset": params.offset}

            if params.status is not None:
                where_parts.append("r.status = :status")
                values["status"] = params.status
            if params.mode is not None:
                where_parts.append("r.mode = :mode")
                values["mode"] = params.mode

            where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

            rows = conn.execute(
                text(f"""
                    SELECT r.id, s.vendor_name, r.mode, r.status,
                           r.requested_start_date, r.requested_end_date,
                           r.symbols_requested, r.symbols_succeeded, r.symbols_failed,
                           r.bars_upserted, r.errors, r.error_message,
                           r.duration_seconds, r.started_at, r.finished_at
                    FROM market_data.vendor_bar_runs r
                    JOIN market_data.vendor_bar_sources s ON s.id = r.vendor_source_id
                    {where_clause}
                    ORDER BY r.id DESC
                    LIMIT :limit OFFSET :offset
                """),
                values,
            ).mappings().all()
    finally:
        engine.dispose()

    items = [_run_to_item(row) for row in rows]
    return {
        "items": items,
        "limit": params.limit,
        "offset": params.offset,
        "count": len(items),
    }


def get_ingest_run(run_id: int) -> dict[str, Any] | None:
    from sqlalchemy import text

    engine = _engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT r.id, s.vendor_name, r.mode, r.status,
                           r.requested_start_date, r.requested_end_date,
                           r.symbols_requested, r.symbols_succeeded, r.symbols_failed,
                           r.bars_upserted, r.errors, r.error_message,
                           r.duration_seconds, r.started_at, r.finished_at
                    FROM market_data.vendor_bar_runs r
                    JOIN market_data.vendor_bar_sources s ON s.id = r.vendor_source_id
                    WHERE r.id = :run_id
                """),
                {"run_id": run_id},
            ).mappings().first()
    finally:
        engine.dispose()

    if row is None:
        return None
    return _run_to_item(row)


def get_latest_ingest_run() -> dict[str, Any] | None:
    from sqlalchemy import text

    engine = _engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT r.id, s.vendor_name, r.mode, r.status,
                           r.requested_start_date, r.requested_end_date,
                           r.symbols_requested, r.symbols_succeeded, r.symbols_failed,
                           r.bars_upserted, r.errors, r.error_message,
                           r.duration_seconds, r.started_at, r.finished_at
                    FROM market_data.vendor_bar_runs r
                    JOIN market_data.vendor_bar_sources s ON s.id = r.vendor_source_id
                    ORDER BY r.id DESC
                    LIMIT 1
                """),
            ).mappings().first()
    finally:
        engine.dispose()

    if row is None:
        return None
    return _run_to_item(row)


def get_missing_bars(ticker: str | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    from sqlalchemy import text

    engine = _engine()
    try:
        with engine.connect() as conn:
            values: dict[str, Any] = {"limit": limit, "offset": offset}
            where_clause = ""
            if ticker is not None:
                where_clause = "WHERE m.ticker = :ticker"
                values["ticker"] = ticker

            rows = conn.execute(
                text(f"""
                    SELECT m.id, m.symbol_id, m.ticker, m.bar_date,
                           m.reason, m.vendor_bar_run_id, m.created_at
                    FROM market_data.missing_bars m
                    {where_clause}
                    ORDER BY m.bar_date DESC, m.ticker ASC
                    LIMIT :limit OFFSET :offset
                """),
                values,
            ).mappings().all()
    finally:
        engine.dispose()

    items = [
        {
            "id": int(row["id"]),
            "symbol_id": int(row["symbol_id"]),
            "ticker": row["ticker"],
            "bar_date": str(row["bar_date"]),
            "reason": row["reason"],
            "run_id": int(row["vendor_bar_run_id"]) if row["vendor_bar_run_id"] else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]
    return {"items": items, "limit": limit, "offset": offset, "count": len(items)}


def get_bar_date_range() -> dict[str, Any] | None:
    from sqlalchemy import text

    engine = _engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT MIN(bar_date) AS first_date,
                           MAX(bar_date) AS last_date,
                           COUNT(*) AS total_bars,
                           COUNT(DISTINCT bar_date) AS unique_days
                    FROM market_data.daily_bars
                """)
            ).mappings().first()
    finally:
        engine.dispose()

    if row is None or row["first_date"] is None:
        return None

    return {
        "first_date": str(row["first_date"]),
        "last_date": str(row["last_date"]),
        "total_bars": int(row["total_bars"]),
        "unique_days": int(row["unique_days"]),
    }


def get_backfill_progress(from_date: str = "2025-06-01") -> dict[str, Any]:
    from datetime import date, timedelta
    from sqlalchemy import text

    start = date.fromisoformat(from_date)
    yesterday = date.today() - timedelta(days=1)

    engine = _engine()
    try:
        with engine.connect() as conn:
            # Build trading calendar: dates where >=5 symbols have bars
            trading_days_rows = conn.execute(
                text("""
                    SELECT bar_date
                    FROM market_data.daily_bars
                    WHERE bar_date >= :start AND bar_date <= :end
                      AND adjustment_type = 'unadjusted'
                    GROUP BY bar_date
                    HAVING COUNT(DISTINCT symbol_id) >= 5
                    ORDER BY bar_date
                """),
                {"start": start, "end": yesterday},
            ).scalars().all()
            trading_days = set(trading_days_rows)
            trading_day_count = len(trading_days)

            # Fall back to weekday count if no calendar yet
            if trading_day_count == 0:
                trading_day_count = sum(
                    1 for i in range((yesterday - start).days + 1)
                    if (start + timedelta(days=i)).weekday() < 5
                )

            # Active symbols
            active_symbols = conn.execute(
                text("SELECT COUNT(*) FROM symbol_master.symbols WHERE active = true")
            ).scalar_one()

            # Per-symbol: count bars and first bar date
            per_symbol = conn.execute(
                text("""
                    SELECT s.canonical_ticker AS ticker,
                           s.id AS symbol_id,
                           COUNT(d.bar_date) AS bars_have,
                           MIN(d.bar_date) AS first_bar_date
                    FROM symbol_master.symbols s
                    LEFT JOIN market_data.daily_bars d
                        ON d.symbol_id = s.id
                       AND d.bar_date >= :start
                       AND d.bar_date <= :end
                       AND d.adjustment_type = 'unadjusted'
                    WHERE s.active = true
                    GROUP BY s.id, s.canonical_ticker
                    ORDER BY s.canonical_ticker
                """),
                {"start": start, "end": yesterday},
            ).mappings().all()
    finally:
        engine.dispose()

    # Compute per-symbol expected bars using trading calendar
    results = []
    total_bars_have = 0
    total_expected = 0
    symbols_complete = 0
    symbols_partial = 0
    symbols_empty = 0

    for r in per_symbol:
        bars_have = int(r["bars_have"])
        first_bar = r["first_bar_date"]
        total_bars_have += bars_have

        if trading_days and first_bar is not None:
            # Only count trading days from this symbol's first bar onward
            expected = sum(1 for d in trading_days if d >= first_bar)
        else:
            expected = trading_day_count

        total_expected += expected
        bars_missing = max(expected - bars_have, 0)

        if bars_have == 0:
            symbols_empty += 1
        elif bars_have >= expected:
            symbols_complete += 1
        else:
            symbols_partial += 1

        results.append({
            "ticker": r["ticker"],
            "symbol_id": int(r["symbol_id"]),
            "bars_have": bars_have,
            "bars_expected": expected,
            "bars_missing": bars_missing,
        })

    # Sort by most missing first
    results.sort(key=lambda x: (-x["bars_missing"], x["ticker"]))

    pct = (total_bars_have / total_expected * 100) if total_expected > 0 else 0.0

    return {
        "from_date": str(start),
        "to_date": str(yesterday),
        "trading_days_in_range": trading_day_count,
        "active_symbols": active_symbols,
        "total_bars_expected": total_expected,
        "total_bars_have": total_bars_have,
        "total_bars_missing": max(total_expected - total_bars_have, 0),
        "percent_complete": round(pct, 2),
        "symbols_complete": symbols_complete,
        "symbols_partial": symbols_partial,
        "symbols_empty": symbols_empty,
        "by_symbol": results,
    }


def _bar_to_item(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "symbol_id": int(row["symbol_id"]),
        "ticker": row["ticker"],
        "bar_date": str(row["bar_date"]),
        "adjustment_type": row["adjustment_type"],
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": int(row["volume"]),
        "vwap": float(row["vwap"]) if row["vwap"] is not None else None,
        "transactions": int(row["transactions"]) if row["transactions"] is not None else None,
        "fetched_at": row["fetched_at"].isoformat() if row["fetched_at"] else None,
        "run_id": int(row["vendor_bar_run_id"]) if row["vendor_bar_run_id"] else None,
    }


def _run_to_item(row: Any) -> dict[str, Any]:
    return {
        "run_id": int(row["id"]),
        "vendor": row["vendor_name"],
        "mode": row["mode"],
        "status": row["status"],
        "from_date": str(row["requested_start_date"]),
        "to_date": str(row["requested_end_date"]),
        "symbols_requested": row["symbols_requested"],
        "symbols_succeeded": row["symbols_succeeded"],
        "symbols_failed": row["symbols_failed"],
        "bars_upserted": row["bars_upserted"],
        "errors": row["errors"],
        "error_message": row["error_message"],
        "duration_seconds": row["duration_seconds"],
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
    }
