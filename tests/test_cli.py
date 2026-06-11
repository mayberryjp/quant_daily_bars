"""Tests for CLI parser construction."""

from datetime import date

from quant_daily_bars._cli_impl import build_parser, _contiguous_ranges


class TestCLIParser:
    def test_db_upgrade_parses(self):
        parser = build_parser()
        args = parser.parse_args(["db", "upgrade"])
        assert args.command == "db"
        assert args.db_command == "upgrade"

    def test_db_verify_parses(self):
        parser = build_parser()
        args = parser.parse_args(["db", "verify"])
        assert args.db_command == "verify"

    def test_bars_ingest_parses(self):
        parser = build_parser()
        args = parser.parse_args([
            "bars", "ingest",
            "--from-date", "2024-01-01",
            "--to-date", "2024-01-31",
            "--tickers", "AAPL,MSFT",
            "--dry-run",
        ])
        assert args.command == "bars"
        assert args.bars_command == "ingest"
        assert str(args.from_date) == "2024-01-01"
        assert str(args.to_date) == "2024-01-31"
        assert args.tickers == "AAPL,MSFT"
        assert args.dry_run is True

    def test_bars_ingest_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["bars", "ingest", "--from-date", "2024-01-01"])
        assert args.to_date is None
        assert args.tickers is None
        assert args.adjustment_type == "unadjusted"
        assert args.mode == "backfill"
        assert args.dry_run is False

    def test_bars_run_summary_parses(self):
        parser = build_parser()
        args = parser.parse_args(["bars", "run-summary", "--latest"])
        assert args.bars_command == "run-summary"
        assert args.latest is True

    def test_scheduled_mode_no_from_date(self):
        parser = build_parser()
        args = parser.parse_args(["bars", "ingest", "--schedule", "86400"])
        assert args.from_date is None
        assert args.schedule == 86400

    def test_backfill_gaps_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["bars", "backfill-gaps"])
        assert args.bars_command == "backfill-gaps"
        assert args.from_date == date(2025, 6, 1)
        assert getattr(args, "schedule", None) is None

    def test_backfill_gaps_with_schedule(self):
        parser = build_parser()
        args = parser.parse_args(["bars", "backfill-gaps", "--schedule", "86400"])
        assert args.schedule == 86400
        assert args.from_date == date(2025, 6, 1)

    def test_backfill_gaps_custom_from_date(self):
        parser = build_parser()
        args = parser.parse_args(["bars", "backfill-gaps", "--from-date", "2024-01-01"])
        assert args.from_date == date(2024, 1, 1)

    def test_ingest_new_symbols_parses(self):
        parser = build_parser()
        args = parser.parse_args([
            "bars", "ingest-new-symbols",
            "--from-date", "2024-01-01",
        ])
        assert args.bars_command == "ingest-new-symbols"
        assert args.from_date == date(2024, 1, 1)
        assert args.to_date is None
        assert args.adjustment_type == "unadjusted"

    def test_ingest_new_symbols_with_to_date(self):
        parser = build_parser()
        args = parser.parse_args([
            "bars", "ingest-new-symbols",
            "--from-date", "2024-01-01",
            "--to-date", "2024-06-30",
            "--adjustment-type", "split_adjusted",
        ])
        assert args.from_date == date(2024, 1, 1)
        assert args.to_date == date(2024, 6, 30)
        assert args.adjustment_type == "split_adjusted"


class TestContiguousRanges:
    def test_empty(self):
        assert _contiguous_ranges([]) == []

    def test_single_date(self):
        result = _contiguous_ranges([date(2024, 1, 2)])
        assert result == [(date(2024, 1, 2), date(2024, 1, 2))]

    def test_contiguous_weekdays(self):
        dates = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)]
        result = _contiguous_ranges(dates)
        assert result == [(date(2024, 1, 2), date(2024, 1, 5))]

    def test_weekend_bridge(self):
        # Fri Jan 5 -> Mon Jan 8 should be one range (gap=3)
        dates = [date(2024, 1, 5), date(2024, 1, 8)]
        result = _contiguous_ranges(dates)
        assert result == [(date(2024, 1, 5), date(2024, 1, 8))]

    def test_gap_splits_ranges(self):
        # Jan 2-3, then skip a week, Jan 10-11
        dates = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 10), date(2024, 1, 11)]
        result = _contiguous_ranges(dates)
        assert len(result) == 2
        assert result[0] == (date(2024, 1, 2), date(2024, 1, 3))
        assert result[1] == (date(2024, 1, 10), date(2024, 1, 11))
