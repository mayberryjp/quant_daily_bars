"""Polygon daily bars client.

Retrieval-only client for /v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}.
Handles pagination, timeout, retry/backoff, rate-limit, and structured errors.
Performs no database writes.
"""

from __future__ import annotations

import collections
import logging
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from quant_daily_bars.vendors.polygon.config import PolygonConfig
from quant_daily_bars.vendors.polygon.errors import (
    PolygonAuthError,
    PolygonHTTPError,
    PolygonRateLimitError,
    PolygonServerError,
)
from quant_daily_bars.vendors.polygon.models import AggregatesPage
from quant_daily_bars.vendors.polygon.transport import (
    Transport,
    UrllibTransport,
    decode_json_body,
)


SleepFunc = Callable[[float], None]

log = logging.getLogger(__name__)


class PolygonBarsClient:
    """Retrieval-only Polygon daily bars client.

    This class performs no database writes. It isolates HTTP concerns and returns
    typed aggregate pages for later ingestion code.
    """

    def __init__(
        self,
        config: PolygonConfig,
        *,
        transport: Transport | None = None,
        sleep: SleepFunc | None = None,
    ) -> None:
        self.config = config
        self._transport = transport or UrllibTransport()
        self._sleep = sleep or time.sleep
        self._clock = time.monotonic
        # Sliding window: track timestamps of the last N requests
        self._request_timestamps: collections.deque[float] = collections.deque()

    @classmethod
    def from_env(cls, *, transport: Transport | None = None, sleep: SleepFunc | None = None) -> "PolygonBarsClient":
        return cls(PolygonConfig.from_env(require_api_key=True), transport=transport, sleep=sleep)

    def get_daily_bars(
        self,
        *,
        ticker: str,
        from_date: date,
        to_date: date,
        adjusted: bool = False,
        limit: int = 50000,
    ) -> AggregatesPage:
        """Fetch daily bars for a single ticker over a date range."""
        path = f"/v2/aggs/ticker/{ticker}/range/1/day/{from_date.isoformat()}/{to_date.isoformat()}"
        params: dict[str, Any] = {
            "adjusted": str(adjusted).lower(),
            "sort": "asc",
            "limit": limit,
        }
        url = self._with_api_key(self._build_url(path, params))
        log.info("requesting daily bars  ticker=%s  from=%s  to=%s", ticker, from_date, to_date)
        payload = self._request_json(url)
        fetched_at = datetime.now(timezone.utc)
        return AggregatesPage.from_payload(payload, ticker=ticker, fetched_at=fetched_at)

    def iter_daily_bars(
        self,
        *,
        ticker: str,
        from_date: date,
        to_date: date,
        adjusted: bool = False,
        limit: int = 50000,
    ) -> Iterator[AggregatesPage]:
        """Yield paginated daily bar pages for a ticker."""
        path = f"/v2/aggs/ticker/{ticker}/range/1/day/{from_date.isoformat()}/{to_date.isoformat()}"
        params: dict[str, Any] = {
            "adjusted": str(adjusted).lower(),
            "sort": "asc",
            "limit": limit,
        }
        next_url: str | None = self._build_url(path, params)
        pages_seen = 0

        while next_url:
            request_url = self._with_api_key(next_url)
            log.info("requesting page %d  url=%s", pages_seen + 1, self._redact_api_key(request_url))
            payload = self._request_json(request_url)
            fetched_at = datetime.now(timezone.utc)
            page = AggregatesPage.from_payload(payload, ticker=ticker, fetched_at=fetched_at)
            yield page
            pages_seen += 1
            next_url = page.next_url

    def _throttle(self) -> None:
        """Enforce sliding-window rate limit (default: 5 req/60s for Polygon free tier)."""
        rpm = self.config.rate_limit_rpm
        if rpm <= 0:
            return
        window = 60.0
        now = self._clock()
        # Discard timestamps older than the window
        while self._request_timestamps and now - self._request_timestamps[0] >= window:
            self._request_timestamps.popleft()
        if len(self._request_timestamps) >= rpm:
            oldest = self._request_timestamps[0]
            wait = window - (now - oldest) + 0.1  # +0.1s safety margin
            if wait > 0:
                log.info("rate limit: %d/%d requests in window, waiting %.1fs", len(self._request_timestamps), rpm, wait)
                self._sleep(wait)
                # Re-check after sleeping
                now = self._clock()
                while self._request_timestamps and now - self._request_timestamps[0] >= window:
                    self._request_timestamps.popleft()
        self._request_timestamps.append(self._clock())

    def _request_json(self, url: str) -> dict[str, object]:
        max_attempts = self.config.retry_count + 1
        for attempt in range(max_attempts):
            self._throttle()
            response = self._transport.request(
                "GET",
                url,
                headers={"Accept": "application/json", "User-Agent": "quant-daily-bars/0.1"},
                timeout=self.config.timeout_seconds,
            )

            if 200 <= response.status_code < 300:
                return decode_json_body(response)

            body: object | None
            try:
                body = decode_json_body(response)
            except Exception:
                body = response.body.decode("utf-8", errors="replace")

            if response.status_code in (401, 403):
                raise PolygonAuthError(
                    "Polygon authentication failed",
                    status_code=response.status_code,
                    body=body,
                )

            retry_after = _retry_after_seconds(response.headers)
            if response.status_code == 429:
                if attempt < max_attempts - 1:
                    wait = retry_after if retry_after is not None else self._backoff_for(attempt)
                    log.warning("rate limited (429)  attempt=%d/%d  waiting=%.1fs", attempt + 1, max_attempts, wait)
                    self._sleep(wait)
                    continue
                raise PolygonRateLimitError(
                    "Polygon rate limit exceeded after all retries",
                    status_code=response.status_code,
                    body=body,
                    retry_after_seconds=retry_after,
                )

            if 500 <= response.status_code < 600:
                if attempt < max_attempts - 1:
                    wait = self._backoff_for(attempt)
                    log.warning("server error (%d)  attempt=%d/%d  waiting=%.1fs", response.status_code, attempt + 1, max_attempts, wait)
                    self._sleep(wait)
                    continue
                raise PolygonServerError(
                    "Polygon server error after retries",
                    status_code=response.status_code,
                    body=body,
                )

            raise PolygonHTTPError(
                "Polygon HTTP request failed",
                status_code=response.status_code,
                body=body,
                retry_after_seconds=retry_after,
            )

        raise AssertionError("unreachable retry loop exit")

    def _build_url(self, path: str, params: Mapping[str, Any]) -> str:
        base = self.config.base_url.rstrip("/") + "/"
        url = urljoin(base, path.lstrip("/"))
        if params:
            return f"{url}?{urlencode(params)}"
        return url

    def _with_api_key(self, url: str) -> str:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["apiKey"] = self.config.api_key
        return urlunparse(parsed._replace(query=urlencode(query)))

    def _redact_api_key(self, url: str) -> str:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if "apiKey" in query:
            query["apiKey"] = "<redacted>"
        return urlunparse(parsed._replace(query=urlencode(query)))

    def _backoff_for(self, attempt: int) -> float:
        return self.config.backoff_seconds * (self.config.backoff_multiplier ** attempt)


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    retry_after = None
    for key, value in headers.items():
        if key.lower() == "retry-after":
            retry_after = value
            break
    if retry_after is None:
        return None
    try:
        seconds = float(retry_after)
    except ValueError:
        return None
    return max(seconds, 0.0)
