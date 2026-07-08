"""Bottle API application for quant_daily_bars."""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any, Callable, Dict, Optional, Union

from bottle import Bottle, request, response

from quant_daily_bars.api.readiness import (
    ReadinessStatus,
    check_database_readiness,
    sanitize_readiness_error,
)
from quant_daily_bars.api.bars import (
    BarListParams,
    IngestRunListParams,
    get_backfill_progress,
    get_bar_date_range,
    get_bar_summary,
    get_coverage_gaps,
    get_gap_dates,
    get_gap_symbols,
    get_ingest_run,
    get_latest_ingest_run,
    get_missing_bars,
    list_bars,
    list_ingest_runs,
    list_tickers_coverage,
)
from quant_daily_bars.api.ingest_jobs import (
    IngestTriggerError,
    IngestTriggerParams,
    get_ingest_job,
    list_ingest_jobs,
    submit_ingest_job,
)

SERVICE_NAME = "quant-daily-bars-api"

log = logging.getLogger(SERVICE_NAME)

# Type aliases for dependency injection (testing)
ReadinessCheck = Callable[[], Union[ReadinessStatus, Dict[str, Any]]]
BarList = Callable[[BarListParams], Dict[str, Any]]
BarSummary = Callable[[str], Optional[Dict[str, Any]]]
BarDateRange = Callable[[], Optional[Dict[str, Any]]]
TickersCoverage = Callable[[], Dict[str, Any]]
IngestRuns = Callable[[IngestRunListParams], Dict[str, Any]]
IngestRunDetail = Callable[[int], Optional[Dict[str, Any]]]
IngestLatest = Callable[[], Optional[Dict[str, Any]]]
MissingBars = Callable[..., Dict[str, Any]]
BackfillProgress = Callable[..., Dict[str, Any]]
CoverageGaps = Callable[..., Optional[Dict[str, Any]]]
GapSymbols = Callable[..., Optional[Dict[str, Any]]]
GapDates = Callable[..., Optional[Dict[str, Any]]]
IngestSubmit = Callable[[IngestTriggerParams], Dict[str, Any]]
IngestJobDetail = Callable[[str], Optional[Dict[str, Any]]]
IngestJobList = Callable[..., Dict[str, Any]]

VALID_RUN_STATUSES = frozenset(("running", "completed", "failed", "cancelled"))
VALID_ADJUSTMENT_TYPES = frozenset(("unadjusted", "split_adjusted"))


# ---------------------------------------------------------------------------
# Query-parameter helpers
# ---------------------------------------------------------------------------

class _ValidationError(Exception):
    pass


def _int_param(raw: str | None, *, default: int, ge: int | None = None, le: int | None = None) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise _ValidationError("invalid integer parameter")
    if ge is not None and value < ge:
        raise _ValidationError(f"value must be >= {ge}")
    if le is not None and value > le:
        raise _ValidationError(f"value must be <= {le}")
    return value


def _status_param(raw: str | None) -> str | None:
    if raw is None or raw == "":
        return None
    if raw not in VALID_RUN_STATUSES:
        raise _ValidationError(f"status must be one of {sorted(VALID_RUN_STATUSES)}")
    return raw


def _adjustment_param(raw: str | None) -> str | None:
    if raw is None or raw == "":
        return None
    if raw not in VALID_ADJUSTMENT_TYPES:
        raise _ValidationError(f"adjustment_type must be one of {sorted(VALID_ADJUSTMENT_TYPES)}")
    return raw


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _status_payload(status: Union[ReadinessStatus, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(status, ReadinessStatus):
        return status.as_json()
    return {"status": "ok", **status}


def _not_found(error: str = "not found") -> dict:
    response.status = 404
    return {"status": "not_found", "error": error}


def _server_error(exc: Exception) -> dict:
    log.exception("handler_error: %s", exc)
    response.status = 500
    return {
        "status": "error",
        "error": sanitize_readiness_error(exc, os.environ.get("DATABASE_URL")),
    }


def _validation_error_response(detail: str = "validation error") -> dict:
    response.status = 422
    return {"detail": detail}


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app(
    readiness_check: ReadinessCheck = check_database_readiness,
    bar_list: BarList = list_bars,
    bar_summary: BarSummary = get_bar_summary,
    bar_date_range_fn: BarDateRange = get_bar_date_range,
    tickers_coverage: TickersCoverage = list_tickers_coverage,
    ingest_runs: IngestRuns = list_ingest_runs,
    ingest_run_detail: IngestRunDetail = get_ingest_run,
    ingest_latest: IngestLatest = get_latest_ingest_run,
    missing_bars_fn: MissingBars = get_missing_bars,
    backfill_progress_fn: BackfillProgress = get_backfill_progress,
    coverage_gaps_fn: CoverageGaps = get_coverage_gaps,
    gap_symbols_fn: GapSymbols = get_gap_symbols,
    gap_dates_fn: GapDates = get_gap_dates,
    ingest_submit_fn: IngestSubmit = submit_ingest_job,
    ingest_job_detail_fn: IngestJobDetail = get_ingest_job,
    ingest_jobs_list_fn: IngestJobList = list_ingest_jobs,
) -> Bottle:
    api = Bottle()
    api.title = SERVICE_NAME

    # -- request logging hooks ------------------------------------------

    @api.hook("before_request")
    def _log_before() -> None:
        request._log_start = time.perf_counter()  # type: ignore[attr-defined]
        log.info(
            "request_start method=%s path=%s query=%s",
            request.method, request.path, request.query_string,
        )

    @api.hook("after_request")
    def _log_after() -> None:
        start = getattr(request, "_log_start", None)
        if start is not None:
            duration_ms = (time.perf_counter() - start) * 1000
            log.info(
                "request_end method=%s path=%s status=%d duration_ms=%.1f",
                request.method, request.path, response.status_code, duration_ms,
            )

    # -- health / readiness ---------------------------------------------

    @api.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": SERVICE_NAME}

    @api.get("/ready")
    def ready() -> dict:
        try:
            return _status_payload(readiness_check())
        except Exception as exc:
            response.status = 503
            return {
                "status": "not_ready",
                "database": "error",
                "error": sanitize_readiness_error(exc, os.environ.get("DATABASE_URL")),
            }

    # -- bars data -------------------------------------------------------

    @api.get("/bars")
    def bars_route() -> dict:
        try:
            limit = _int_param(request.query.get("limit"), default=100, ge=1, le=500)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
            adjustment_type = _adjustment_param(request.query.get("adjustment_type"))
        except _ValidationError as exc:
            return _validation_error_response(str(exc))

        ticker = request.query.get("ticker") or None
        symbol_id_raw = request.query.get("symbol_id")
        symbol_id = None
        if symbol_id_raw:
            try:
                symbol_id = int(symbol_id_raw)
            except (ValueError, TypeError):
                return _validation_error_response("symbol_id must be an integer")

        params = BarListParams(
            ticker=ticker,
            symbol_id=symbol_id,
            from_date=request.query.get("from_date") or None,
            to_date=request.query.get("to_date") or None,
            adjustment_type=adjustment_type,
            limit=limit,
            offset=offset,
        )
        try:
            return bar_list(params)
        except Exception as exc:
            return _server_error(exc)

    @api.get("/bars/summary/<ticker>")
    def bars_summary_route(ticker: str) -> dict:
        try:
            result = bar_summary(ticker)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found(f"no bars for ticker {ticker}")
        return result

    @api.get("/bars/date-range")
    def bars_date_range_route() -> dict:
        try:
            result = bar_date_range_fn()
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("no bars in database")
        return result

    @api.get("/bars/coverage")
    def bars_coverage_route() -> dict:
        try:
            return tickers_coverage()
        except Exception as exc:
            return _server_error(exc)

    @api.get("/bars/backfill-progress")
    def bars_backfill_progress_route() -> dict:
        from_date = request.query.get("from_date") or "2025-06-01"
        try:
            return backfill_progress_fn(from_date=from_date)
        except Exception as exc:
            return _server_error(exc)

    @api.get("/bars/coverage-gaps")
    def bars_coverage_gaps_route() -> dict:
        try:
            limit = _int_param(request.query.get("limit"), default=1000, ge=1, le=5000)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
            adjustment_type = _adjustment_param(request.query.get("adjustment_type"))
        except _ValidationError as exc:
            return _validation_error_response(str(exc))

        reference_ticker = request.query.get("ticker") or "MSFT"
        try:
            result = coverage_gaps_fn(
                reference_ticker=reference_ticker,
                from_date=request.query.get("from_date") or None,
                to_date=request.query.get("to_date") or None,
                adjustment_type=adjustment_type or "unadjusted",
                limit=limit,
                offset=offset,
            )
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found(f"no bars for reference ticker {reference_ticker}")
        return result

    @api.get("/bars/gaps/symbols")
    def bars_gap_symbols_route() -> dict:
        try:
            limit = _int_param(request.query.get("limit"), default=50, ge=1, le=1000)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
            adjustment_type = _adjustment_param(request.query.get("adjustment_type"))
        except _ValidationError as exc:
            return _validation_error_response(str(exc))

        reference_ticker = request.query.get("ticker") or "MSFT"
        try:
            result = gap_symbols_fn(
                reference_ticker=reference_ticker,
                from_date=request.query.get("from_date") or None,
                to_date=request.query.get("to_date") or None,
                adjustment_type=adjustment_type or "unadjusted",
                limit=limit,
                offset=offset,
            )
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found(f"no bars for reference ticker {reference_ticker}")
        return result

    @api.get("/bars/gaps/dates")
    def bars_gap_dates_route() -> dict:
        try:
            limit = _int_param(request.query.get("limit"), default=50, ge=1, le=1000)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
            adjustment_type = _adjustment_param(request.query.get("adjustment_type"))
        except _ValidationError as exc:
            return _validation_error_response(str(exc))

        reference_ticker = request.query.get("ticker") or "MSFT"
        try:
            result = gap_dates_fn(
                reference_ticker=reference_ticker,
                from_date=request.query.get("from_date") or None,
                to_date=request.query.get("to_date") or None,
                adjustment_type=adjustment_type or "unadjusted",
                limit=limit,
                offset=offset,
            )
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found(f"no bars for reference ticker {reference_ticker}")
        return result

    # -- ingest runs -----------------------------------------------------

    @api.get("/ingest/runs")
    def ingest_runs_route() -> dict:
        try:
            status = _status_param(request.query.get("status"))
            limit = _int_param(request.query.get("limit"), default=20, ge=1, le=100)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
        except _ValidationError as exc:
            return _validation_error_response(str(exc))

        params = IngestRunListParams(
            status=status,
            mode=request.query.get("mode") or None,
            limit=limit,
            offset=offset,
        )
        try:
            return ingest_runs(params)
        except Exception as exc:
            return _server_error(exc)

    @api.get("/ingest/runs/<run_id>")
    def ingest_run_detail_route(run_id: str) -> dict:
        try:
            rid = int(run_id)
        except (ValueError, TypeError):
            return _validation_error_response("run_id must be an integer")
        try:
            result = ingest_run_detail(rid)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("ingest run not found")
        return result

    @api.get("/ingest/latest")
    def ingest_latest_route() -> dict:
        try:
            result = ingest_latest()
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("no ingest runs found")
        return {"status": "ok", "latest": result}

    # -- ingest trigger (async) -----------------------------------------

    @api.post("/ingest")
    def ingest_trigger_route() -> dict:
        try:
            body = request.json
        except Exception:
            return _validation_error_response("invalid JSON body")
        if body is None:
            return _validation_error_response("a JSON body is required")
        try:
            params = IngestTriggerParams.from_body(body)
        except IngestTriggerError as exc:
            return _validation_error_response(str(exc))
        try:
            job = ingest_submit_fn(params)
        except Exception as exc:
            return _server_error(exc)
        response.status = 202
        return {"status": "accepted", "job": job}

    @api.get("/ingest/jobs")
    def ingest_jobs_list_route() -> dict:
        try:
            limit = _int_param(request.query.get("limit"), default=50, ge=1, le=200)
        except _ValidationError as exc:
            return _validation_error_response(str(exc))
        try:
            return ingest_jobs_list_fn(limit=limit)
        except Exception as exc:
            return _server_error(exc)

    @api.get("/ingest/jobs/<job_id>")
    def ingest_job_detail_route(job_id: str) -> dict:
        try:
            result = ingest_job_detail_fn(job_id)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("ingest job not found")
        return result

    # -- missing bars ----------------------------------------------------

    @api.get("/missing-bars")
    def missing_bars_route() -> dict:
        try:
            limit = _int_param(request.query.get("limit"), default=100, ge=1, le=500)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
        except _ValidationError as exc:
            return _validation_error_response(str(exc))

        ticker = request.query.get("ticker") or None
        try:
            return missing_bars_fn(ticker=ticker, limit=limit, offset=offset)
        except Exception as exc:
            return _server_error(exc)

    return api


# ---------------------------------------------------------------------------
# Module-level setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
    force=True,
)

print(
    f"[{SERVICE_NAME}] module={__file__} python={sys.executable} "
    f"version={sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    file=sys.stderr,
    flush=True,
)

app = create_app()


if __name__ == "__main__":
    from waitress import serve

    host = os.environ.get("API_LISTEN_ADDRESS", "0.0.0.0")
    port = int(os.environ.get("API_PORT", "8000"))
    log.info("Starting API server on %s:%d...", host, port)
    serve(app, host=host, port=port, threads=20)
