"""CLI implementation for quant_daily_bars."""

from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path


EXPECTED_SCHEMA_VERSION = "0001_daily_bars_market_data"
EXPECTED_TABLES = (
    "corporate_actions",
    "daily_bars",
    "missing_bars",
    "vendor_bar_runs",
    "vendor_bar_sources",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://quant:quant_dev_password@localhost:5432/quant",
    )


def _alembic_config() -> object:
    from alembic.config import Config

    config = Config(str(_repo_root() / "alembic.ini"))
    config.set_main_option("script_location", str(_repo_root() / "alembic"))
    return config


def _engine() -> object:
    try:
        from sqlalchemy import create_engine
    except ModuleNotFoundError as exc:
        raise SystemExit("SQLAlchemy is required for database commands") from exc
    return create_engine(_database_url(), pool_pre_ping=True)


# ── db commands ─────────────────────────────────────────────────────────────

def db_upgrade(_args: argparse.Namespace) -> None:
    from alembic import command
    command.upgrade(_alembic_config(), "head")


def db_downgrade_base(_args: argparse.Namespace) -> None:
    from alembic import command
    command.downgrade(_alembic_config(), "base")


def db_verify(_args: argparse.Namespace) -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(_database_url(), pool_pre_ping=True)
    expected_table_names = tuple(sorted(EXPECTED_TABLES))

    with engine.connect() as connection:
        connection.execute(text("SELECT 1")).scalar_one()
        schema_version = connection.execute(
            text("SELECT version_num FROM market_data.alembic_version_daily_bars")
        ).scalar_one()
        tables = connection.execute(
            text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'market_data'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
        ).scalars().all()
        vendor_sources = connection.execute(
            text("SELECT count(*) FROM market_data.vendor_bar_sources")
        ).scalar_one()

    if schema_version != EXPECTED_SCHEMA_VERSION:
        raise SystemExit(
            f"schema_version={schema_version} expected={EXPECTED_SCHEMA_VERSION}"
        )
    if tuple(tables) != expected_table_names:
        raise SystemExit(f"tables={','.join(tables)} expected={','.join(expected_table_names)}")

    print(
        "postgres=ok "
        f"schema_version={schema_version} "
        f"tables={len(tables)} "
        f"vendor_bar_sources={vendor_sources}"
    )


# ── bars commands ───────────────────────────────────────────────────────────

def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date: {value} (use YYYY-MM-DD)") from exc


def bars_ingest(args: argparse.Namespace) -> None:
    from quant_daily_bars.ingest.job import DailyBarIngestJob, IngestOptions
    from quant_daily_bars.vendors.polygon.client import PolygonBarsClient
    from quant_daily_bars.vendors.polygon.errors import (
        PolygonAuthError,
        PolygonConfigError,
        PolygonRateLimitError,
    )

    interval = getattr(args, "schedule", None)
    run_once = interval is None

    # In one-shot mode, --from-date is required.
    if run_once and args.from_date is None and not args.fixture:
        raise SystemExit("error: --from-date is required for one-shot ingestion (or use --schedule for daily auto-ingest)")

    while True:
        # In scheduled mode, automatically compute yesterday's date each cycle.
        if args.from_date is not None:
            from_date = args.from_date
        else:
            from_date = date.today() - timedelta(days=1)
        to_date = args.to_date or from_date
        tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None

        options = IngestOptions(
            from_date=from_date,
            to_date=to_date,
            tickers=tickers,
            adjustment_type=args.adjustment_type,
            mode="incremental" if interval and not args.from_date else args.mode,
            fixture_path=args.fixture,
            dry_run=args.dry_run,
        )

        logging.getLogger(__name__).info(
            "ingesting bars  from=%s  to=%s  mode=%s", from_date, to_date, options.mode,
        )

        engine = None if args.dry_run and not args.fixture else _engine()
        client = None
        if not args.fixture:
            try:
                client = PolygonBarsClient.from_env()
            except PolygonConfigError as exc:
                print(f"ERROR: {exc}")
                print("  Hint: set MASSIVE_API_KEY in your environment or .env file.")
                if run_once:
                    raise SystemExit(1) from exc
                if interval:
                    time.sleep(interval)
                continue

        job = DailyBarIngestJob(engine=engine, client=client)
        try:
            summary = job.run(options)
            print(summary.format_line())
            if summary.warnings:
                for w in summary.warnings:
                    print(f"  WARNING: {w}")
            if summary.failures:
                for f in summary.failures[:10]:
                    print(f"  FAILURE: {f}")
            if summary.status == "failed" and run_once:
                raise SystemExit(1)
        except PolygonAuthError as exc:
            print(f"ERROR: {exc} (HTTP {exc.status_code})")
            print("  Hint: your MASSIVE_API_KEY may be invalid or expired.")
            if run_once:
                raise SystemExit(1) from exc
        except PolygonRateLimitError as exc:
            print(f"ERROR: {exc} (HTTP {exc.status_code})")
            if exc.retry_after_seconds is not None:
                print(f"  Hint: retry after {exc.retry_after_seconds:.0f}s.")
            if run_once:
                raise SystemExit(1) from exc
        except ConnectionError as exc:
            print(f"ERROR: could not connect to Polygon API: {exc}")
            if run_once:
                raise SystemExit(1) from exc
        except Exception as exc:
            from quant_daily_bars.ingest.summary import IngestSummary
            summary = IngestSummary(mode=options.mode, status="failed", errors=1, error_message=str(exc))
            print(summary.format_line())
            print(f"ERROR: {exc}")
            if run_once:
                raise SystemExit(1) from exc

        if run_once:
            break

        logging.getLogger(__name__).info("next ingest in %d seconds", interval)
        time.sleep(interval)


def bars_run_summary(args: argparse.Namespace) -> None:
    from quant_daily_bars.ingest.job import DailyBarIngestJob

    if not args.latest:
        raise SystemExit("only --latest is currently supported")

    job = DailyBarIngestJob(engine=_engine())
    row = job.latest_run_summary()
    if row is None:
        print("bars_run_summary=empty")
        return
    print(
        "bars_run_summary=ok "
        f"run_id={row['id']} "
        f"vendor={row['vendor']} "
        f"mode={row['mode']} "
        f"status={row['status']} "
        f"symbols_requested={row['symbols_requested']} "
        f"symbols_succeeded={row['symbols_succeeded']} "
        f"symbols_failed={row['symbols_failed']} "
        f"bars_upserted={row['bars_upserted']} "
        f"errors={row['errors']}"
    )


# ── parser ──────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m quant_daily_bars.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # db subcommands
    db_parser = subparsers.add_parser("db")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)

    upgrade_parser = db_subparsers.add_parser("upgrade")
    upgrade_parser.set_defaults(func=db_upgrade)

    verify_parser = db_subparsers.add_parser("verify")
    verify_parser.set_defaults(func=db_verify)

    downgrade_parser = db_subparsers.add_parser("downgrade-base")
    downgrade_parser.set_defaults(func=db_downgrade_base)

    # bars subcommands
    bars_parser = subparsers.add_parser("bars")
    bars_subparsers = bars_parser.add_subparsers(dest="bars_command", required=True)

    ingest_parser = bars_subparsers.add_parser("ingest")
    ingest_parser.add_argument("--from-date", type=_parse_date, default=None, help="Start date (YYYY-MM-DD). Required for one-shot; defaults to yesterday in scheduled mode.")
    ingest_parser.add_argument("--to-date", type=_parse_date, default=None, help="End date (YYYY-MM-DD, default: same as from-date)")
    ingest_parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers (default: all active)")
    ingest_parser.add_argument("--adjustment-type", choices=("unadjusted", "split_adjusted"), default="unadjusted")
    ingest_parser.add_argument("--mode", choices=("backfill", "incremental"), default="backfill")
    ingest_parser.add_argument("--fixture", help="Path to fixture file or directory")
    ingest_parser.add_argument("--dry-run", action="store_true", help="Parse bars without database writes")
    ingest_parser.add_argument(
        "--schedule", type=int, metavar="SECONDS",
        help="Run continuously, sleeping SECONDS between ingests. Automatically ingests previous day's bars each cycle.",
    )
    ingest_parser.set_defaults(func=bars_ingest)

    run_summary_parser = bars_subparsers.add_parser("run-summary")
    run_summary_parser.add_argument("--latest", action="store_true", required=True)
    run_summary_parser.set_defaults(func=bars_run_summary)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        level=logging.INFO,
    )
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0
