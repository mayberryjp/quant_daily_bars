"""Tests for the stale-run cleanup sweep (no DB required)."""

from quant_daily_bars.ingest.maintenance import cancel_stale_runs


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows, captured):
        self._rows = rows
        self._captured = captured

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, params=None):
        self._captured["sql"] = str(statement)
        self._captured["params"] = params
        return _FakeResult(self._rows)


class _FakeEngine:
    def __init__(self, rows):
        self._rows = rows
        self.captured = {}

    def begin(self):
        return _FakeConn(self._rows, self.captured)


class TestCancelStaleRuns:
    def test_returns_cancelled_ids(self):
        engine = _FakeEngine(rows=[(1,), (2,), (3,)])
        ids = cancel_stale_runs(engine, stale_after_minutes=45)
        assert ids == [1, 2, 3]
        assert engine.captured["params"]["minutes"] == 45

    def test_default_threshold(self):
        engine = _FakeEngine(rows=[])
        assert cancel_stale_runs(engine) == []
        assert engine.captured["params"]["minutes"] == 30

    def test_sql_targets_running_and_marks_cancelled(self):
        engine = _FakeEngine(rows=[])
        cancel_stale_runs(engine)
        sql = engine.captured["sql"]
        assert "status = 'cancelled'" in sql
        assert "status = 'running'" in sql
        assert "make_interval" in sql
        assert "heartbeat_at" in sql

    def test_custom_reason_passed_through(self):
        engine = _FakeEngine(rows=[(9,)])
        cancel_stale_runs(engine, reason="manual cleanup")
        assert engine.captured["params"]["reason"] == "manual cleanup"
