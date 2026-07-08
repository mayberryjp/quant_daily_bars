"""Async, thread-pool-backed ingestion job runner for the API.

Lets the HTTP API trigger daily-bar ingestion without blocking the request
thread. Each submitted job runs in a background worker drawn from a bounded
thread pool (``INGEST_MAX_WORKERS``), so multiple ingestions can execute
concurrently. Job state is tracked in an in-process registry that clients poll
via ``GET /ingest/jobs/<job_id>``.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable

log = logging.getLogger(__name__)

VALID_ADJUSTMENT_TYPES = frozenset(("unadjusted", "split_adjusted"))
VALID_MODES = frozenset(("backfill", "incremental"))

_MAX_JOB_HISTORY = 200
_DEFAULT_MAX_WORKERS = 4

# Terminal + in-flight states for a job.
STATE_QUEUED = "queued"
STATE_RUNNING = "running"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"


class IngestTriggerError(ValueError):
    """Raised when ingestion trigger parameters are invalid."""


def _parse_date(value: Any, field_name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError) as exc:
        raise IngestTriggerError(f"{field_name} must be an ISO date (YYYY-MM-DD)") from exc


def _parse_tickers(raw: Any) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        items = [t.strip() for t in raw.split(",") if t.strip()]
    elif isinstance(raw, (list, tuple)):
        items = [str(t).strip() for t in raw if str(t).strip()]
    else:
        raise IngestTriggerError("tickers must be a JSON array or comma-separated string")
    return items or None


@dataclass(frozen=True)
class IngestTriggerParams:
    """Validated parameters for an ingestion trigger request."""

    from_date: date
    to_date: date
    tickers: list[str] | None = None
    adjustment_type: str = "unadjusted"
    mode: str = "backfill"

    @classmethod
    def from_body(cls, body: Any) -> "IngestTriggerParams":
        if not isinstance(body, dict):
            raise IngestTriggerError("request body must be a JSON object")

        from_raw = body.get("from_date")
        if not from_raw:
            raise IngestTriggerError("from_date is required")
        from_date = _parse_date(from_raw, "from_date")

        to_raw = body.get("to_date")
        to_date = _parse_date(to_raw, "to_date") if to_raw else from_date
        if to_date < from_date:
            raise IngestTriggerError("to_date must be on or after from_date")

        adjustment_type = body.get("adjustment_type") or "unadjusted"
        if adjustment_type not in VALID_ADJUSTMENT_TYPES:
            raise IngestTriggerError(
                f"adjustment_type must be one of {sorted(VALID_ADJUSTMENT_TYPES)}"
            )

        mode = body.get("mode") or "backfill"
        if mode not in VALID_MODES:
            raise IngestTriggerError(f"mode must be one of {sorted(VALID_MODES)}")

        return cls(
            from_date=from_date,
            to_date=to_date,
            tickers=_parse_tickers(body.get("tickers")),
            adjustment_type=adjustment_type,
            mode=mode,
        )


@dataclass
class _JobRecord:
    job_id: str
    params: IngestTriggerParams
    state: str = STATE_QUEUED
    submitted_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    run_id: int | None = None
    summary: dict[str, Any] | None = None
    error: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summary_to_dict(summary: Any) -> dict[str, Any]:
    return {
        "status": summary.status,
        "mode": summary.mode,
        "symbols_requested": summary.symbols_requested,
        "symbols_succeeded": summary.symbols_succeeded,
        "symbols_failed": summary.symbols_failed,
        "bars_upserted": summary.bars_upserted,
        "missing_bars_recorded": summary.missing_bars_recorded,
        "errors": summary.errors,
        "duration_seconds": summary.duration_seconds,
        "warnings": list(summary.warnings),
        "failures": list(summary.failures[:10]),
    }


def _run_ingest_job(params: IngestTriggerParams) -> tuple[int | None, dict[str, Any]]:
    """Default job runner: execute a live ingestion against the DB and Polygon."""
    from quant_daily_bars.api.bars import _engine
    from quant_daily_bars.ingest.job import DailyBarIngestJob, IngestOptions
    from quant_daily_bars.vendors.polygon.client import PolygonBarsClient

    engine = _engine()
    try:
        client = PolygonBarsClient.from_env()
        options = IngestOptions(
            from_date=params.from_date,
            to_date=params.to_date,
            tickers=params.tickers,
            adjustment_type=params.adjustment_type,
            mode=params.mode,
        )
        job = DailyBarIngestJob(engine=engine, client=client)
        summary = job.run(options)
        return summary.run_id, _summary_to_dict(summary)
    finally:
        engine.dispose()


class IngestJobManager:
    """Bounded thread pool + registry for async ingestion jobs."""

    def __init__(
        self,
        max_workers: int | None = None,
        job_runner: Callable[[IngestTriggerParams], tuple[int | None, dict[str, Any]]] | None = None,
    ) -> None:
        if max_workers is None:
            try:
                max_workers = int(os.environ.get("INGEST_MAX_WORKERS", str(_DEFAULT_MAX_WORKERS)))
            except ValueError:
                max_workers = _DEFAULT_MAX_WORKERS
        max_workers = max(1, max_workers)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ingest")
        self._lock = threading.Lock()
        self._jobs: "OrderedDict[str, _JobRecord]" = OrderedDict()
        self._job_runner = job_runner or _run_ingest_job

    def submit(self, params: IngestTriggerParams) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        record = _JobRecord(job_id=job_id, params=params, submitted_at=_now_iso())
        with self._lock:
            self._jobs[job_id] = record
            self._prune_locked()
            snapshot = _record_to_dict(record)
        self._executor.submit(self._execute, job_id)
        return snapshot

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._jobs.get(job_id)
            return _record_to_dict(record) if record is not None else None

    def list_jobs(self, limit: int = 50) -> dict[str, Any]:
        with self._lock:
            records = list(self._jobs.values())
        recent = records[-limit:][::-1]  # newest first
        return {"items": [_record_to_dict(r) for r in recent], "count": len(recent)}

    def _execute(self, job_id: str) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            record.state = STATE_RUNNING
            record.started_at = _now_iso()
            params = record.params
        try:
            run_id, summary = self._job_runner(params)
            with self._lock:
                record = self._jobs.get(job_id)
                if record is not None:
                    record.run_id = run_id
                    record.summary = summary
                    record.state = STATE_FAILED if summary.get("status") == "failed" else STATE_COMPLETED
                    record.finished_at = _now_iso()
        except Exception as exc:  # noqa: BLE001 - surface any failure to the job record
            log.exception("ingest job %s failed", job_id)
            with self._lock:
                record = self._jobs.get(job_id)
                if record is not None:
                    record.state = STATE_FAILED
                    record.error = str(exc)
                    record.finished_at = _now_iso()

    def _prune_locked(self) -> None:
        while len(self._jobs) > _MAX_JOB_HISTORY:
            self._jobs.popitem(last=False)


def _record_to_dict(record: _JobRecord) -> dict[str, Any]:
    p = record.params
    return {
        "job_id": record.job_id,
        "state": record.state,
        "from_date": p.from_date.isoformat(),
        "to_date": p.to_date.isoformat(),
        "tickers": list(p.tickers) if p.tickers else None,
        "adjustment_type": p.adjustment_type,
        "mode": p.mode,
        "submitted_at": record.submitted_at,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "run_id": record.run_id,
        "summary": record.summary,
        "error": record.error,
    }


# ── Lazy module-level singleton ─────────────────────────────────────────────

_default_manager: IngestJobManager | None = None
_manager_lock = threading.Lock()


def get_default_manager() -> IngestJobManager:
    global _default_manager
    if _default_manager is None:
        with _manager_lock:
            if _default_manager is None:
                _default_manager = IngestJobManager()
    return _default_manager


def submit_ingest_job(params: IngestTriggerParams) -> dict[str, Any]:
    return get_default_manager().submit(params)


def get_ingest_job(job_id: str) -> dict[str, Any] | None:
    return get_default_manager().get(job_id)


def list_ingest_jobs(limit: int = 50) -> dict[str, Any]:
    return get_default_manager().list_jobs(limit=limit)
