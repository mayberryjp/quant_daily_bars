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
