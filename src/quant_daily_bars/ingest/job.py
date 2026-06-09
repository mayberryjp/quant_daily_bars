"""Daily bar ingestion job.

Implements backfill and incremental ingest of OHLCV daily bars from Polygon
into the market_data.daily_bars table with idempotent upserts.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Engine

from quant_daily_bars.ingest.summary import IngestSummary
from quant_daily_bars.vendors.polygon.client import PolygonBarsClient
from quant_daily_bars.vendors.polygon.errors import PolygonError
from quant_daily_bars.vendors.polygon.models import AggregateBar


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestTarget:
    """A symbol to ingest bars for."""
    symbol_id: int
    ticker: str


@dataclass(frozen=True)
class IngestOptions:
    """Parameters for a bar ingestion run."""
    from_date: date
    to_date: date
    tickers: list[str] | None = None  # None means use all active symbols from symbol_master
    adjustment_type: str = "unadjusted"
    mode: str = "backfill"  # 'backfill' or 'incremental'
    fixture_path: str | None = None
    dry_run: bool = False


# ── Upsert SQL ──────────────────────────────────────────────────────────────

UPSERT_DAILY_BAR = text("""
    INSERT INTO market_data.daily_bars (
        symbol_id, ticker, bar_date, adjustment_type,
        open, high, low, close, volume, vwap, transactions,
        vendor_source_id, vendor_bar_run_id, fetched_at, updated_at
    ) VALUES (
        :symbol_id, :ticker, :bar_date, :adjustment_type,
        :open, :high, :low, :close, :volume, :vwap, :transactions,
        :vendor_source_id, :vendor_bar_run_id, :fetched_at, now()
    )
    ON CONFLICT (symbol_id, bar_date, adjustment_type)
    DO UPDATE SET
        ticker = EXCLUDED.ticker,
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        vwap = EXCLUDED.vwap,
        transactions = EXCLUDED.transactions,
        vendor_bar_run_id = EXCLUDED.vendor_bar_run_id,
        fetched_at = EXCLUDED.fetched_at,
        updated_at = now()
""")

UPSERT_MISSING_BAR = text("""
    INSERT INTO market_data.missing_bars (
        symbol_id, ticker, bar_date, vendor_source_id, vendor_bar_run_id, reason
    ) VALUES (
        :symbol_id, :ticker, :bar_date, :vendor_source_id, :vendor_bar_run_id, :reason
    )
    ON CONFLICT (symbol_id, bar_date, vendor_source_id)
    DO UPDATE SET
        vendor_bar_run_id = EXCLUDED.vendor_bar_run_id,
        reason = EXCLUDED.reason
""")


class DailyBarIngestJob:
    """Orchestrates daily bar ingestion from Polygon into Postgres."""

    def __init__(self, *, engine: Engine | None = None, client: PolygonBarsClient | None = None) -> None:
        self._engine = engine
        self._client = client

    def run(self, options: IngestOptions) -> IngestSummary:
        started = time.monotonic()
        summary = IngestSummary(mode=options.mode)

        if options.fixture_path:
            return self._run_fixture(options, summary, started)

        if self._engine is None:
            raise RuntimeError("Database engine is required for live ingestion")
        if self._client is None:
            raise RuntimeError("Polygon client is required for live ingestion")

        targets = self._resolve_targets(options)
        summary.symbols_requested = len(targets)

        if not targets:
            log.warning("no symbols to ingest")
            summary.duration_seconds = time.monotonic() - started
            return summary

        run_id = self._create_run(options, len(targets))

        for target in targets:
            try:
                bars_count = self._ingest_symbol(target, options, run_id)
                summary.bars_upserted += bars_count
                summary.symbols_succeeded += 1
                if bars_count == 0:
                    self._record_missing(target, options, run_id, "no bars returned by vendor")
                    summary.missing_bars_recorded += 1
                    summary.warnings.append(f"{target.ticker}: no bars returned")
            except PolygonError as exc:
                summary.symbols_failed += 1
                summary.errors += 1
                summary.failures.append(f"{target.ticker}: {exc}")
                log.error("failed to ingest %s: %s", target.ticker, exc)
            except Exception as exc:
                summary.symbols_failed += 1
                summary.errors += 1
                summary.failures.append(f"{target.ticker}: {exc}")
                log.error("unexpected error ingesting %s: %s", target.ticker, exc, exc_info=True)

        self._finalize_run(run_id, summary)
        summary.status = "failed" if summary.errors > 0 and summary.symbols_succeeded == 0 else "ok"
        summary.duration_seconds = time.monotonic() - started
        return summary

    def _resolve_targets(self, options: IngestOptions) -> list[IngestTarget]:
        """Resolve symbol targets for ingestion."""
        assert self._engine is not None
        if options.tickers:
            # Look up symbol_ids for the requested tickers
            with self._engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT id, ticker FROM symbol_master.symbols
                        WHERE ticker = ANY(:tickers)
                    """),
                    {"tickers": options.tickers},
                ).fetchall()
                found = {r[1] for r in rows}
                targets = [IngestTarget(symbol_id=r[0], ticker=r[1]) for r in rows]
                missing = set(options.tickers) - found
                if missing:
                    log.warning("tickers not found in symbol_master: %s", ", ".join(sorted(missing)))
                return targets
        else:
            # All active symbols
            with self._engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT id, ticker FROM symbol_master.symbols
                        WHERE is_active = true
                        ORDER BY ticker
                    """)
                ).fetchall()
                return [IngestTarget(symbol_id=r[0], ticker=r[1]) for r in rows]

    def _create_run(self, options: IngestOptions, symbols_count: int) -> int:
        """Create a vendor_bar_runs record and return its id."""
        assert self._engine is not None
        with self._engine.begin() as conn:
            row = conn.execute(
                text("""
                    INSERT INTO market_data.vendor_bar_runs (
                        vendor_source_id, mode, requested_start_date, requested_end_date,
                        symbols_requested
                    ) VALUES (
                        (SELECT id FROM market_data.vendor_bar_sources WHERE vendor_name = 'polygon'),
                        :mode, :start_date, :end_date, :symbols_count
                    ) RETURNING id
                """),
                {
                    "mode": options.mode,
                    "start_date": options.from_date,
                    "end_date": options.to_date,
                    "symbols_count": symbols_count,
                },
            ).scalar_one()
            return row

    def _ingest_symbol(self, target: IngestTarget, options: IngestOptions, run_id: int) -> int:
        """Fetch and upsert daily bars for one symbol. Returns count of bars upserted."""
        assert self._client is not None
        assert self._engine is not None

        adjusted = options.adjustment_type == "split_adjusted"
        bars_upserted = 0

        for page in self._client.iter_daily_bars(
            ticker=target.ticker,
            from_date=options.from_date,
            to_date=options.to_date,
            adjusted=adjusted,
        ):
            if not page.results:
                continue

            with self._engine.begin() as conn:
                vendor_source_id = conn.execute(
                    text("SELECT id FROM market_data.vendor_bar_sources WHERE vendor_name = 'polygon'")
                ).scalar_one()

                for bar in page.results:
                    conn.execute(
                        UPSERT_DAILY_BAR,
                        {
                            "symbol_id": target.symbol_id,
                            "ticker": target.ticker,
                            "bar_date": bar.bar_date,
                            "adjustment_type": options.adjustment_type,
                            "open": bar.open,
                            "high": bar.high,
                            "low": bar.low,
                            "close": bar.close,
                            "volume": bar.volume,
                            "vwap": bar.vwap,
                            "transactions": bar.transactions,
                            "vendor_source_id": vendor_source_id,
                            "vendor_bar_run_id": run_id,
                            "fetched_at": page.fetched_at,
                        },
                    )
                    bars_upserted += 1

        log.info("ingested %d bars for %s", bars_upserted, target.ticker)
        return bars_upserted

    def _record_missing(self, target: IngestTarget, options: IngestOptions, run_id: int, reason: str) -> None:
        """Record a missing bar entry for operator inspection."""
        assert self._engine is not None
        with self._engine.begin() as conn:
            vendor_source_id = conn.execute(
                text("SELECT id FROM market_data.vendor_bar_sources WHERE vendor_name = 'polygon'")
            ).scalar_one()
            conn.execute(
                UPSERT_MISSING_BAR,
                {
                    "symbol_id": target.symbol_id,
                    "ticker": target.ticker,
                    "bar_date": options.from_date,
                    "vendor_source_id": vendor_source_id,
                    "vendor_bar_run_id": run_id,
                    "reason": reason,
                },
            )

    def _finalize_run(self, run_id: int, summary: IngestSummary) -> None:
        """Update the vendor_bar_runs record with final counts."""
        assert self._engine is not None
        with self._engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE market_data.vendor_bar_runs
                    SET status = :status,
                        symbols_succeeded = :succeeded,
                        symbols_failed = :failed,
                        bars_upserted = :bars,
                        errors = :errors,
                        error_message = :error_message,
                        duration_seconds = :duration,
                        finished_at = now()
                    WHERE id = :run_id
                """),
                {
                    "status": summary.status if summary.status != "ok" else "completed",
                    "succeeded": summary.symbols_succeeded,
                    "failed": summary.symbols_failed,
                    "bars": summary.bars_upserted,
                    "errors": summary.errors,
                    "error_message": "; ".join(summary.failures[:5]) if summary.failures else None,
                    "duration": summary.duration_seconds,
                    "run_id": run_id,
                },
            )

    def _run_fixture(self, options: IngestOptions, summary: IngestSummary, started: float) -> IngestSummary:
        """Process bars from a local fixture file (JSON) for testing without API or DB."""
        import json
        from pathlib import Path

        fixture_path = Path(options.fixture_path)  # type: ignore[arg-type]
        if fixture_path.is_dir():
            files = sorted(fixture_path.glob("*.json"))
        else:
            files = [fixture_path]

        for fpath in files:
            log.info("loading fixture %s", fpath)
            with open(fpath) as f:
                data = json.load(f)

            ticker = data.get("ticker", fpath.stem)
            results = data.get("results", [])
            summary.symbols_requested += 1

            from quant_daily_bars.vendors.polygon.models import AggregateBar

            bars = []
            for item in results:
                try:
                    bars.append(AggregateBar.from_payload(item, ticker=ticker))
                except Exception as exc:
                    summary.errors += 1
                    summary.failures.append(f"{ticker}: {exc}")

            if options.dry_run:
                summary.bars_upserted += len(bars)
                summary.symbols_succeeded += 1
                for bar in bars:
                    print(f"  {bar.ticker}  {bar.bar_date}  O={bar.open} H={bar.high} L={bar.low} C={bar.close} V={bar.volume}")
            elif self._engine is not None:
                run_id = self._create_run(options, 1)
                # Resolve or synthesize symbol_id
                with self._engine.begin() as conn:
                    row = conn.execute(
                        text("SELECT id FROM symbol_master.symbols WHERE ticker = :ticker"),
                        {"ticker": ticker},
                    ).fetchone()
                    if row is None:
                        log.warning("ticker %s not in symbol_master, skipping DB write", ticker)
                        summary.symbols_failed += 1
                        continue
                    symbol_id = row[0]
                    vendor_source_id = conn.execute(
                        text("SELECT id FROM market_data.vendor_bar_sources WHERE vendor_name = 'polygon'")
                    ).scalar_one()

                    for bar in bars:
                        conn.execute(
                            UPSERT_DAILY_BAR,
                            {
                                "symbol_id": symbol_id,
                                "ticker": ticker,
                                "bar_date": bar.bar_date,
                                "adjustment_type": options.adjustment_type,
                                "open": bar.open,
                                "high": bar.high,
                                "low": bar.low,
                                "close": bar.close,
                                "volume": bar.volume,
                                "vwap": bar.vwap,
                                "transactions": bar.transactions,
                                "vendor_source_id": vendor_source_id,
                                "vendor_bar_run_id": run_id,
                                "fetched_at": datetime.now(timezone.utc),
                            },
                        )
                        summary.bars_upserted += 1
                summary.symbols_succeeded += 1
                self._finalize_run(run_id, summary)
            else:
                summary.bars_upserted += len(bars)
                summary.symbols_succeeded += 1

        summary.status = "ok" if summary.errors == 0 else "failed"
        summary.duration_seconds = time.monotonic() - started
        return summary

    def latest_run_summary(self) -> dict[str, Any] | None:
        """Return the latest vendor_bar_runs row as a dict."""
        assert self._engine is not None
        with self._engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT r.id, s.vendor_name as vendor, r.mode, r.status,
                           r.requested_start_date, r.requested_end_date,
                           r.symbols_requested, r.symbols_succeeded, r.symbols_failed,
                           r.bars_upserted, r.errors, r.duration_seconds,
                           r.started_at, r.finished_at
                    FROM market_data.vendor_bar_runs r
                    JOIN market_data.vendor_bar_sources s ON s.id = r.vendor_source_id
                    ORDER BY r.id DESC
                    LIMIT 1
                """)
            ).fetchone()
            if row is None:
                return None
            return dict(row._mapping)
