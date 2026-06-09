"""Structured Polygon vendor client errors."""

from __future__ import annotations

from typing import Any


class PolygonError(Exception):
    """Base error for Polygon vendor access."""


class PolygonConfigError(PolygonError):
    """Raised when vendor configuration is missing or invalid."""


class PolygonTransportError(PolygonError):
    """Raised when the transport cannot complete an HTTP request."""


class PolygonTimeoutError(PolygonTransportError):
    """Raised when the provider request times out."""


class PolygonHTTPError(PolygonError):
    """Raised for non-successful provider HTTP responses."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        body: Any | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.retry_after_seconds = retry_after_seconds


class PolygonAuthError(PolygonHTTPError):
    """Raised when the provider rejects credentials."""


class PolygonRateLimitError(PolygonHTTPError):
    """Raised when rate limits remain after configured retry attempts."""


class PolygonServerError(PolygonHTTPError):
    """Raised when retryable server errors remain after retries."""


class PolygonMalformedPayloadError(PolygonError):
    """Raised when a provider payload does not match the expected endpoint shape."""
