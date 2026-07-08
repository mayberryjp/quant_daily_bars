"""Tests for the daily bars API (no database required)."""

from quant_daily_bars.api.app import create_app
from quant_daily_bars.api.readiness import ReadinessStatus
from quant_daily_bars.api.bars import BarListParams, IngestRunListParams
from quant_daily_bars.api.testing import TestClient


def _ok_readiness():
    return ReadinessStatus(database="ok", schema_version="0002_symbol_backfill_status", tables=6)


def _fake_bar_list(params: BarListParams):
    return {
        "items": [
            {
                "id": 1,
                "symbol_id": 42,
                "ticker": "AAPL",
                "bar_date": "2024-01-02",
                "adjustment_type": "unadjusted",
                "open": 187.15,
                "high": 187.44,
                "low": 185.19,
                "close": 185.56,
                "volume": 82034459,
                "vwap": 186.2453,
                "transactions": 682721,
                "fetched_at": "2024-01-03T00:00:00+00:00",
                "run_id": 1,
            }
        ],
        "limit": params.limit,
        "offset": params.offset,
        "count": 1,
    }


def _fake_bar_summary(ticker: str):
    if ticker == "AAPL":
        return {
            "ticker": "AAPL",
            "symbol_id": 42,
            "first_date": "2024-01-02",
            "last_date": "2024-06-01",
            "bar_count": 125,
            "adjustment_type": "unadjusted",
        }
    return None


def _fake_coverage():
    return {
        "items": [
            {"ticker": "AAPL", "symbol_id": 42, "first_date": "2024-01-02", "last_date": "2024-06-01", "bar_count": 125},
            {"ticker": "MSFT", "symbol_id": 43, "first_date": "2024-01-02", "last_date": "2024-06-01", "bar_count": 120},
        ],
        "count": 2,
    }


def _fake_ingest_runs(params: IngestRunListParams):
    return {
        "items": [
            {
                "run_id": 1,
                "vendor": "polygon",
                "mode": "backfill",
                "status": "completed",
                "from_date": "2024-01-01",
                "to_date": "2024-06-01",
                "symbols_requested": 10,
                "symbols_succeeded": 10,
                "symbols_failed": 0,
                "bars_upserted": 1250,
                "errors": 0,
                "error_message": None,
                "duration_seconds": 120.5,
                "started_at": "2024-06-01T00:00:00+00:00",
                "finished_at": "2024-06-01T00:02:00+00:00",
            }
        ],
        "limit": params.limit,
        "offset": params.offset,
        "count": 1,
    }


def _fake_ingest_run_detail(run_id: int):
    if run_id == 1:
        return {
            "run_id": 1,
            "vendor": "polygon",
            "mode": "backfill",
            "status": "completed",
            "from_date": "2024-01-01",
            "to_date": "2024-06-01",
            "symbols_requested": 10,
            "symbols_succeeded": 10,
            "symbols_failed": 0,
            "bars_upserted": 1250,
            "errors": 0,
            "error_message": None,
            "duration_seconds": 120.5,
            "started_at": "2024-06-01T00:00:00+00:00",
            "finished_at": "2024-06-01T00:02:00+00:00",
        }
    return None


def _fake_missing_bars(ticker=None, limit=100, offset=0):
    return {"items": [], "limit": limit, "offset": offset, "count": 0}


def _fake_bar_date_range():
    return {
        "first_date": "2024-01-02",
        "last_date": "2024-06-01",
        "total_bars": 1250,
        "unique_days": 105,
    }


def _fake_backfill_progress(from_date="2025-06-01"):
    return {
        "from_date": from_date,
        "to_date": "2025-12-31",
        "trading_days_in_range": 150,
        "active_symbols": 10,
        "symbols_queried": 7,
        "symbols_not_queried": 3,
        "symbols_with_bars": 5,
        "symbols_no_bars": 5,
        "total_bars_ingested": 900,
        "percent_symbols_queried": 70.0,
    }


def _fake_coverage_gaps(reference_ticker="MSFT", from_date=None, to_date=None,
                        adjustment_type="unadjusted", limit=1000, offset=0):
    if reference_ticker == "ZZZZ":
        return None
    return {
        "reference_ticker": reference_ticker,
        "adjustment_type": adjustment_type,
        "active_symbols": 10,
        "total_days": 2,
        "days_with_gaps": 1,
        "limit": limit,
        "offset": offset,
        "count": 2,
        "items": [
            {"bar_date": "2024-01-02", "symbols_with_bar": 10, "symbols_missing": 0, "coverage_pct": 100.0},
            {"bar_date": "2024-01-03", "symbols_with_bar": 8, "symbols_missing": 2, "coverage_pct": 80.0},
        ],
    }


def _fake_gap_symbols(reference_ticker="MSFT", from_date=None, to_date=None,
                      adjustment_type="unadjusted", limit=50, offset=0):
    if reference_ticker == "ZZZZ":
        return None
    return {
        "reference_ticker": reference_ticker,
        "adjustment_type": adjustment_type,
        "trading_days": 2517,
        "limit": limit,
        "offset": offset,
        "count": 2,
        "items": [
            {"symbol_id": 7, "ticker": "FOO", "first_date": "2018-05-01", "last_date": "2025-07-07",
             "expected_days": 1800, "present_days": 1700, "gap_days": 100, "gap_pct": 5.56},
            {"symbol_id": 9, "ticker": "BAR", "first_date": "2020-01-02", "last_date": "2025-07-07",
             "expected_days": 1380, "present_days": 1360, "gap_days": 20, "gap_pct": 1.45},
        ],
    }


def _fake_gap_dates(reference_ticker="MSFT", from_date=None, to_date=None,
                    adjustment_type="unadjusted", limit=50, offset=0):
    if reference_ticker == "ZZZZ":
        return None
    return {
        "reference_ticker": reference_ticker,
        "adjustment_type": adjustment_type,
        "trading_days": 2517,
        "limit": limit,
        "offset": offset,
        "count": 2,
        "items": [
            {"bar_date": "2021-03-15", "symbols_expected": 480, "symbols_present": 410,
             "symbols_missing": 70, "gap_pct": 14.58},
            {"bar_date": "2019-08-02", "symbols_expected": 450, "symbols_present": 420,
             "symbols_missing": 30, "gap_pct": 6.67},
        ],
    }


def _fake_ingest_latest():
    return {
        "run_id": 1,
        "vendor": "polygon",
        "mode": "backfill",
        "status": "completed",
        "from_date": "2024-01-01",
        "to_date": "2024-06-01",
        "symbols_requested": 10,
        "symbols_succeeded": 10,
        "symbols_failed": 0,
        "bars_upserted": 1250,
        "errors": 0,
        "error_message": None,
        "duration_seconds": 120.5,
        "started_at": "2024-06-01T00:00:00+00:00",
        "finished_at": "2024-06-01T00:02:00+00:00",
    }


def _make_client():
    app = create_app(
        readiness_check=_ok_readiness,
        bar_list=_fake_bar_list,
        bar_summary=_fake_bar_summary,
        bar_date_range_fn=_fake_bar_date_range,
        tickers_coverage=_fake_coverage,
        ingest_runs=_fake_ingest_runs,
        ingest_run_detail=_fake_ingest_run_detail,
        ingest_latest=_fake_ingest_latest,
        missing_bars_fn=_fake_missing_bars,
        backfill_progress_fn=_fake_backfill_progress,
        coverage_gaps_fn=_fake_coverage_gaps,
        gap_symbols_fn=_fake_gap_symbols,
        gap_dates_fn=_fake_gap_dates,
    )
    return TestClient(app)


class TestHealth:
    def test_health(self):
        client = _make_client()
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "quant-daily-bars-api"

    def test_ready(self):
        client = _make_client()
        resp = client.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["database"] == "ok"
        assert data["tables"] == 6

    def test_ready_failure(self):
        def _fail():
            raise RuntimeError("db down")

        app = create_app(readiness_check=_fail)
        client = TestClient(app)
        resp = client.get("/ready")
        assert resp.status_code == 503
        assert resp.json()["status"] == "not_ready"


class TestBarsEndpoints:
    def test_list_bars(self):
        client = _make_client()
        resp = client.get("/bars")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["ticker"] == "AAPL"

    def test_list_bars_with_params(self):
        client = _make_client()
        resp = client.get("/bars", params={"ticker": "AAPL", "from_date": "2024-01-01", "limit": "10"})
        assert resp.status_code == 200

    def test_bars_summary(self):
        client = _make_client()
        resp = client.get("/bars/summary/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["bar_count"] == 125

    def test_bars_summary_not_found(self):
        client = _make_client()
        resp = client.get("/bars/summary/ZZZZ")
        assert resp.status_code == 404

    def test_bars_coverage(self):
        client = _make_client()
        resp = client.get("/bars/coverage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

    def test_invalid_limit(self):
        client = _make_client()
        resp = client.get("/bars", params={"limit": "abc"})
        assert resp.status_code == 422


class TestIngestRunsEndpoints:
    def test_list_runs(self):
        client = _make_client()
        resp = client.get("/ingest/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["status"] == "completed"

    def test_run_detail(self):
        client = _make_client()
        resp = client.get("/ingest/runs/1")
        assert resp.status_code == 200
        assert resp.json()["run_id"] == 1

    def test_run_detail_not_found(self):
        client = _make_client()
        resp = client.get("/ingest/runs/999")
        assert resp.status_code == 404

    def test_run_detail_invalid_id(self):
        client = _make_client()
        resp = client.get("/ingest/runs/abc")
        assert resp.status_code == 422

    def test_latest_run(self):
        client = _make_client()
        resp = client.get("/ingest/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["latest"]["run_id"] == 1
        assert data["latest"]["status"] == "completed"
        assert data["latest"]["started_at"] is not None
        assert data["latest"]["finished_at"] is not None

    def test_latest_run_empty(self):
        app = create_app(
            readiness_check=_ok_readiness,
            ingest_latest=lambda: None,
        )
        client = TestClient(app)
        resp = client.get("/ingest/latest")
        assert resp.status_code == 404


class TestMissingBarsEndpoint:
    def test_missing_bars(self):
        client = _make_client()
        resp = client.get("/missing-bars")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    def test_missing_bars_with_ticker(self):
        client = _make_client()
        resp = client.get("/missing-bars", params={"ticker": "AAPL"})
        assert resp.status_code == 200


class TestBarDateRange:
    def test_date_range(self):
        client = _make_client()
        resp = client.get("/bars/date-range")
        assert resp.status_code == 200
        data = resp.json()
        assert data["first_date"] == "2024-01-02"
        assert data["last_date"] == "2024-06-01"
        assert data["total_bars"] == 1250
        assert data["unique_days"] == 105

    def test_date_range_empty(self):
        app = create_app(
            readiness_check=_ok_readiness,
            bar_date_range_fn=lambda: None,
        )
        client = TestClient(app)
        resp = client.get("/bars/date-range")
        assert resp.status_code == 404


class TestBackfillProgress:
    def test_backfill_progress(self):
        client = _make_client()
        resp = client.get("/bars/backfill-progress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_symbols"] == 10
        assert data["symbols_queried"] == 7
        assert data["symbols_not_queried"] == 3
        assert data["symbols_with_bars"] == 5
        assert data["total_bars_ingested"] == 900
        assert data["percent_symbols_queried"] == 70.0

    def test_backfill_progress_custom_date(self):
        client = _make_client()
        resp = client.get("/bars/backfill-progress", params={"from_date": "2024-01-01"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["from_date"] == "2024-01-01"


class TestCoverageGaps:
    def test_coverage_gaps_default(self):
        client = _make_client()
        resp = client.get("/bars/coverage-gaps")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reference_ticker"] == "MSFT"
        assert data["active_symbols"] == 10
        assert data["count"] == 2
        assert data["items"][0]["symbols_missing"] == 0
        assert data["items"][1]["symbols_missing"] == 2
        assert data["items"][1]["coverage_pct"] == 80.0

    def test_coverage_gaps_custom_ticker(self):
        client = _make_client()
        resp = client.get("/bars/coverage-gaps", params={"ticker": "AAPL"})
        assert resp.status_code == 200
        assert resp.json()["reference_ticker"] == "AAPL"

    def test_coverage_gaps_not_found(self):
        client = _make_client()
        resp = client.get("/bars/coverage-gaps", params={"ticker": "ZZZZ"})
        assert resp.status_code == 404

    def test_coverage_gaps_invalid_limit(self):
        client = _make_client()
        resp = client.get("/bars/coverage-gaps", params={"limit": "99999"})
        assert resp.status_code == 422


class TestGapRankings:
    def test_gap_symbols_default(self):
        client = _make_client()
        resp = client.get("/bars/gaps/symbols")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reference_ticker"] == "MSFT"
        assert data["count"] == 2
        assert data["items"][0]["ticker"] == "FOO"
        assert data["items"][0]["gap_days"] == 100

    def test_gap_symbols_custom_ticker(self):
        client = _make_client()
        resp = client.get("/bars/gaps/symbols", params={"ticker": "AAPL"})
        assert resp.status_code == 200
        assert resp.json()["reference_ticker"] == "AAPL"

    def test_gap_symbols_not_found(self):
        client = _make_client()
        resp = client.get("/bars/gaps/symbols", params={"ticker": "ZZZZ"})
        assert resp.status_code == 404

    def test_gap_symbols_invalid_limit(self):
        client = _make_client()
        resp = client.get("/bars/gaps/symbols", params={"limit": "0"})
        assert resp.status_code == 422

    def test_gap_dates_default(self):
        client = _make_client()
        resp = client.get("/bars/gaps/dates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reference_ticker"] == "MSFT"
        assert data["count"] == 2
        assert data["items"][0]["bar_date"] == "2021-03-15"
        assert data["items"][0]["symbols_missing"] == 70

    def test_gap_dates_not_found(self):
        client = _make_client()
        resp = client.get("/bars/gaps/dates", params={"ticker": "ZZZZ"})
        assert resp.status_code == 404
