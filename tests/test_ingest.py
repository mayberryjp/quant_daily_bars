"""Tests for fixture-based ingestion (dry-run, no DB required)."""

import json
from datetime import date
from pathlib import Path

from quant_daily_bars.ingest.job import DailyBarIngestJob, IngestOptions


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "polygon"


class TestFixtureDryRun:
    def test_single_fixture_dry_run(self):
        options = IngestOptions(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 5),
            fixture_path=str(FIXTURE_DIR / "AAPL.json"),
            dry_run=True,
        )
        job = DailyBarIngestJob()
        summary = job.run(options)
        assert summary.status == "ok"
        assert summary.symbols_requested == 1
        assert summary.symbols_succeeded == 1
        assert summary.bars_upserted == 5

    def test_directory_fixture_dry_run(self):
        options = IngestOptions(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 5),
            fixture_path=str(FIXTURE_DIR),
            dry_run=True,
        )
        job = DailyBarIngestJob()
        summary = job.run(options)
        assert summary.status == "ok"
        assert summary.symbols_requested == 2
        assert summary.symbols_succeeded == 2
        assert summary.bars_upserted == 8  # 5 AAPL + 3 MSFT


class TestIdempotentDesign:
    """Verify the upsert SQL uses ON CONFLICT for idempotency."""

    def test_upsert_sql_has_on_conflict(self):
        from quant_daily_bars.ingest.job import UPSERT_DAILY_BAR
        sql_text = str(UPSERT_DAILY_BAR.text)
        assert "ON CONFLICT" in sql_text
        assert "DO UPDATE SET" in sql_text

    def test_missing_bar_upsert_has_on_conflict(self):
        from quant_daily_bars.ingest.job import UPSERT_MISSING_BAR
        sql_text = str(UPSERT_MISSING_BAR.text)
        assert "ON CONFLICT" in sql_text


class _FakeSymbols:
    """Stand-in for SymbolsApiClient used to resolve ingest targets."""

    def __init__(self, symbols):
        self._symbols = symbols

    def list_active_symbols(self):
        return [s for s in self._symbols if s.active]

    def get_symbol_by_ticker(self, ticker, active=None):
        for symbol in self._symbols:
            if symbol.ticker == ticker:
                return symbol
        return None


class TestResolveTargets:
    """Target resolution goes through the symbols service, not a DB join."""

    def _job(self):
        from quant_daily_bars.symbols.client import Symbol

        symbols = [
            Symbol(symbol_id=1, ticker="AAPL", active=True),
            Symbol(symbol_id=2, ticker="MSFT", active=True),
            Symbol(symbol_id=3, ticker="OLDCO", active=False),
        ]
        return DailyBarIngestJob(symbols_client=_FakeSymbols(symbols))

    def test_all_active_symbols(self):
        job = self._job()
        options = IngestOptions(from_date=date(2024, 1, 1), to_date=date(2024, 1, 5))
        targets = job._resolve_targets(options)
        assert sorted(t.symbol_id for t in targets) == [1, 2]

    def test_explicit_tickers_skip_unknown(self):
        job = self._job()
        options = IngestOptions(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 5),
            tickers=["MSFT", "NOPE"],
        )
        targets = job._resolve_targets(options)
        assert [(t.symbol_id, t.ticker) for t in targets] == [(2, "MSFT")]
