"""Tests for the async ingestion job manager (no DB or API key required)."""

from datetime import date

from quant_daily_bars.api.ingest_jobs import (
    IngestJobManager,
    IngestTriggerError,
    IngestTriggerParams,
)


class TestIngestTriggerParams:
    def test_from_body_full(self):
        params = IngestTriggerParams.from_body({
            "from_date": "2024-01-03",
            "to_date": "2024-01-05",
            "tickers": ["MSFT", " AAPL "],
            "adjustment_type": "split_adjusted",
            "mode": "incremental",
        })
        assert params.from_date == date(2024, 1, 3)
        assert params.to_date == date(2024, 1, 5)
        assert params.tickers == ["MSFT", "AAPL"]
        assert params.adjustment_type == "split_adjusted"
        assert params.mode == "incremental"

    def test_to_date_defaults_to_from_date(self):
        params = IngestTriggerParams.from_body({"from_date": "2024-01-03"})
        assert params.to_date == date(2024, 1, 3)

    def test_tickers_comma_string(self):
        params = IngestTriggerParams.from_body({"from_date": "2024-01-03", "tickers": "MSFT, AAPL"})
        assert params.tickers == ["MSFT", "AAPL"]

    def test_tickers_empty_list_is_none(self):
        params = IngestTriggerParams.from_body({"from_date": "2024-01-03", "tickers": []})
        assert params.tickers is None

    def test_missing_from_date(self):
        try:
            IngestTriggerParams.from_body({"to_date": "2024-01-05"})
        except IngestTriggerError as exc:
            assert "from_date" in str(exc)
        else:
            raise AssertionError("expected IngestTriggerError")

    def test_bad_range(self):
        try:
            IngestTriggerParams.from_body({"from_date": "2024-01-05", "to_date": "2024-01-01"})
        except IngestTriggerError:
            pass
        else:
            raise AssertionError("expected IngestTriggerError")

    def test_invalid_mode(self):
        try:
            IngestTriggerParams.from_body({"from_date": "2024-01-03", "mode": "nope"})
        except IngestTriggerError:
            pass
        else:
            raise AssertionError("expected IngestTriggerError")

    def test_body_not_object(self):
        try:
            IngestTriggerParams.from_body(["not", "a", "dict"])
        except IngestTriggerError:
            pass
        else:
            raise AssertionError("expected IngestTriggerError")


def _params():
    return IngestTriggerParams(from_date=date(2024, 1, 3), to_date=date(2024, 1, 5), tickers=["MSFT"])


class TestIngestJobManager:
    def test_submit_runs_and_completes(self):
        calls = []

        def runner(params):
            calls.append(params)
            return 42, {"status": "ok", "bars_upserted": 10}

        mgr = IngestJobManager(max_workers=2, job_runner=runner)
        snapshot = mgr.submit(_params())
        assert snapshot["state"] == "queued"
        job_id = snapshot["job_id"]

        mgr._executor.shutdown(wait=True)  # wait for the worker to finish

        record = mgr.get(job_id)
        assert record is not None
        assert record["state"] == "completed"
        assert record["run_id"] == 42
        assert record["summary"]["bars_upserted"] == 10
        assert record["finished_at"] is not None
        assert len(calls) == 1

    def test_failed_summary_marks_failed(self):
        def runner(params):
            return 7, {"status": "failed", "bars_upserted": 0}

        mgr = IngestJobManager(max_workers=1, job_runner=runner)
        job_id = mgr.submit(_params())["job_id"]
        mgr._executor.shutdown(wait=True)

        record = mgr.get(job_id)
        assert record["state"] == "failed"
        assert record["run_id"] == 7

    def test_runner_exception_marks_failed_with_error(self):
        def runner(params):
            raise RuntimeError("boom")

        mgr = IngestJobManager(max_workers=1, job_runner=runner)
        job_id = mgr.submit(_params())["job_id"]
        mgr._executor.shutdown(wait=True)

        record = mgr.get(job_id)
        assert record["state"] == "failed"
        assert record["error"] == "boom"

    def test_get_unknown_job(self):
        mgr = IngestJobManager(max_workers=1, job_runner=lambda p: (1, {"status": "ok"}))
        assert mgr.get("nope") is None

    def test_list_jobs_newest_first(self):
        def runner(params):
            return 1, {"status": "ok"}

        mgr = IngestJobManager(max_workers=1, job_runner=runner)
        first = mgr.submit(_params())["job_id"]
        second = mgr.submit(_params())["job_id"]
        mgr._executor.shutdown(wait=True)

        listing = mgr.list_jobs()
        assert listing["count"] == 2
        assert listing["items"][0]["job_id"] == second
        assert listing["items"][1]["job_id"] == first
