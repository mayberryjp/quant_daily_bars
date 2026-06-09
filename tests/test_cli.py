"""Tests for CLI parser construction."""

from quant_daily_bars._cli_impl import build_parser


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
