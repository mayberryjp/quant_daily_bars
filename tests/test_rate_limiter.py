"""Tests for the shared file-based rate limiter."""

import os
import tempfile

from quant_daily_bars.vendors.polygon.rate_limiter import SharedRateLimiter


class TestSharedRateLimiter:
    def _make_limiter(self, rpm, *, clock=None, sleep=None):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)  # start with no file
        return SharedRateLimiter(
            rpm=rpm,
            rate_file=path,
            sleep=sleep or (lambda _: None),
            clock=clock,
        ), path

    def test_unlimited_never_blocks(self):
        limiter, path = self._make_limiter(0)
        # Should not raise or block
        for _ in range(100):
            limiter.throttle()
        _cleanup(path)

    def test_allows_up_to_rpm(self):
        t = [100.0]

        def clock():
            return t[0]

        limiter, path = self._make_limiter(3, clock=clock)
        # 3 requests should succeed without sleeping
        sleep_calls = []
        limiter._sleep = lambda s: sleep_calls.append(s)

        for _ in range(3):
            limiter.throttle()

        assert sleep_calls == []
        _cleanup(path)

    def test_blocks_when_at_limit(self):
        t = [100.0]

        def clock():
            return t[0]

        sleep_calls = []

        def fake_sleep(s):
            sleep_calls.append(s)
            t[0] += s  # advance clock by sleep duration

        limiter, path = self._make_limiter(2, clock=clock, sleep=fake_sleep)

        # First 2 should pass
        limiter.throttle()
        limiter.throttle()
        assert sleep_calls == []

        # 3rd should block
        limiter.throttle()
        assert len(sleep_calls) == 1
        assert sleep_calls[0] > 0
        _cleanup(path)

    def test_window_expiry(self):
        t = [100.0]

        def clock():
            return t[0]

        limiter, path = self._make_limiter(2, clock=clock)

        limiter.throttle()
        limiter.throttle()

        # Advance past the window
        t[0] = 200.0

        sleep_calls = []
        limiter._sleep = lambda s: sleep_calls.append(s)

        # Should be allowed again without sleeping
        limiter.throttle()
        assert sleep_calls == []
        _cleanup(path)

    def test_state_persists_across_instances(self):
        t = [100.0]

        def clock():
            return t[0]

        limiter1, path = self._make_limiter(2, clock=clock)
        limiter1.throttle()
        limiter1.throttle()

        # New instance reading same file
        limiter2 = SharedRateLimiter(rpm=2, rate_file=path, sleep=lambda _: None, clock=clock)

        sleep_calls = []
        limiter2._sleep = lambda s: (sleep_calls.append(s), t.__setitem__(0, t[0] + s))

        limiter2.throttle()
        assert len(sleep_calls) == 1
        _cleanup(path)


def _cleanup(path: str) -> None:
    for p in (path, path + ".lock", path + ".tmp"):
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass
