"""Cross-process file-based sliding-window rate limiter.

All Polygon client instances (across supervisord workers) coordinate through
a shared lock file so the combined request rate stays within the configured
RPM limit.

On Linux/macOS the lock uses ``fcntl.flock``; on Windows it uses
``msvcrt.locking`` (non-blocking retry loop).
"""

from __future__ import annotations

import json
import logging
import os
import platform
import time
from typing import Callable

log = logging.getLogger(__name__)

_DEFAULT_RATE_FILE = "/tmp/polygon_rate_limiter.json"
_WINDOW = 60.0  # sliding window in seconds


class SharedRateLimiter:
    """File-based sliding-window rate limiter shared across processes.

    Parameters
    ----------
    rpm : int
        Maximum requests per 60-second window (across all processes).
    rate_file : str
        Path to the shared JSON state file.
    sleep : callable
        Overridable sleep function (for testing).
    clock : callable
        Overridable monotonic clock (for testing).
    """

    def __init__(
        self,
        rpm: int,
        *,
        rate_file: str | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.rpm = rpm
        self.rate_file = rate_file or os.environ.get(
            "POLYGON_RATE_FILE", _DEFAULT_RATE_FILE,
        )
        self._sleep = sleep or time.sleep
        # For cross-process timing we need wall-clock time, not monotonic
        self._clock = clock or time.time

    def throttle(self) -> None:
        """Block until a request slot is available, then record it."""
        if self.rpm <= 0:
            return  # unlimited

        while True:
            with _file_lock(self.rate_file + ".lock"):
                timestamps = self._read_timestamps()
                now = self._clock()

                # Discard entries older than the window
                timestamps = [t for t in timestamps if now - t < _WINDOW]

                if len(timestamps) < self.rpm:
                    # Slot available — record and return
                    timestamps.append(now)
                    self._write_timestamps(timestamps)
                    return

                # Need to wait — compute how long
                oldest = timestamps[0]
                wait = _WINDOW - (now - oldest) + 0.1

            log.info(
                "shared rate limit: %d/%d in window, waiting %.1fs",
                len(timestamps), self.rpm, wait,
            )
            self._sleep(wait)

    def _read_timestamps(self) -> list[float]:
        try:
            with open(self.rate_file, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            pass
        return []

    def _write_timestamps(self, timestamps: list[float]) -> None:
        tmp = self.rate_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(timestamps, f)
        os.replace(tmp, self.rate_file)


class _file_lock:
    """Cross-platform file lock context manager."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._fd: int | None = None

    def __enter__(self) -> "_file_lock":
        # Ensure parent directory exists
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        self._fd = os.open(self.path, os.O_CREAT | os.O_RDWR)

        if platform.system() == "Windows":
            import msvcrt
            while True:
                try:
                    msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
                    return self
                except (OSError, IOError):
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._fd is not None:
            if platform.system() == "Windows":
                import msvcrt
                try:
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                except (OSError, IOError):
                    pass
            # On Unix, closing the fd releases the flock automatically
            os.close(self._fd)
            self._fd = None
