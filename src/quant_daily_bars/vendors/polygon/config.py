"""Configuration for the Polygon vendor client."""

from __future__ import annotations

from dataclasses import dataclass
import os


from quant_daily_bars.vendors.polygon.errors import PolygonConfigError


DEFAULT_BASE_URL = "https://api.polygon.io"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_RETRY_COUNT = 3
DEFAULT_BACKOFF_SECONDS = 0.5
DEFAULT_BACKOFF_MULTIPLIER = 2.0
DEFAULT_RATE_LIMIT_RPM = 30


def _env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value in (None, ""):
        return None
    return value


def _float_from_env(name: str, default: float) -> float:
    value = _env_value(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise PolygonConfigError(f"{name} must be a number") from exc
    if parsed < 0:
        raise PolygonConfigError(f"{name} must be non-negative")
    return parsed


def _int_from_env(name: str, default: int) -> int:
    value = _env_value(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise PolygonConfigError(f"{name} must be an integer") from exc
    if parsed < 0:
        raise PolygonConfigError(f"{name} must be non-negative")
    return parsed


@dataclass(frozen=True)
class PolygonConfig:
    """Runtime settings for Polygon HTTP access.

    The API key is intentionally excluded from repr output so accidental logs do
    not expose credentials.
    """

    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    retry_count: int = DEFAULT_RETRY_COUNT
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS
    backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER
    rate_limit_rpm: int = DEFAULT_RATE_LIMIT_RPM

    def __post_init__(self) -> None:
        if not self.base_url:
            raise PolygonConfigError("MASSIVE_BASE_URL is required")
        if self.timeout_seconds <= 0:
            raise PolygonConfigError("MASSIVE_TIMEOUT_SECONDS must be greater than zero")
        if self.retry_count < 0:
            raise PolygonConfigError("MASSIVE_RETRY_COUNT must be non-negative")
        if self.backoff_seconds < 0:
            raise PolygonConfigError("MASSIVE_BACKOFF_SECONDS must be non-negative")
        if self.backoff_multiplier < 1:
            raise PolygonConfigError("MASSIVE_BACKOFF_MULTIPLIER must be at least 1")

    def __repr__(self) -> str:
        return (
            "PolygonConfig("
            "api_key=<redacted>, "
            f"base_url={self.base_url!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, "
            f"retry_count={self.retry_count!r}, "
            f"backoff_seconds={self.backoff_seconds!r}, "
            f"backoff_multiplier={self.backoff_multiplier!r}, "
            f"rate_limit_rpm={self.rate_limit_rpm!r})"
        )

    @classmethod
    def from_env(cls, *, require_api_key: bool = False) -> "PolygonConfig":
        api_key = _env_value("MASSIVE_API_KEY") or ""
        if require_api_key and not api_key:
            raise PolygonConfigError("MASSIVE_API_KEY is required for live Polygon access")

        return cls(
            api_key=api_key,
            base_url=(_env_value("MASSIVE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            timeout_seconds=_float_from_env("MASSIVE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
            retry_count=_int_from_env("MASSIVE_RETRY_COUNT", DEFAULT_RETRY_COUNT),
            backoff_seconds=_float_from_env("MASSIVE_BACKOFF_SECONDS", DEFAULT_BACKOFF_SECONDS),
            backoff_multiplier=_float_from_env(
                "MASSIVE_BACKOFF_MULTIPLIER",
                DEFAULT_BACKOFF_MULTIPLIER,
            ),
            rate_limit_rpm=_int_from_env(
                "MASSIVE_RATE_LIMIT_RPM",
                DEFAULT_RATE_LIMIT_RPM,
            ),
        )
