"""Typed Polygon daily bars response models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict

from quant_daily_bars.vendors.polygon.errors import PolygonMalformedPayloadError


JsonObject = Dict[str, Any]


@dataclass(frozen=True)
class AggregateBar:
    """Single bar from Polygon /v2/aggs/ticker/{ticker}/range/1/day endpoint."""

    ticker: str
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float | None = None
    transactions: int | None = None
    raw: JsonObject = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: JsonObject, *, ticker: str) -> "AggregateBar":
        if not isinstance(payload, dict):
            raise PolygonMalformedPayloadError("bar result must be an object")

        timestamp_ms = payload.get("t")
        if not isinstance(timestamp_ms, (int, float)):
            raise PolygonMalformedPayloadError("bar result is missing timestamp (t)")

        bar_date = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date()

        for field_name in ("o", "h", "l", "c"):
            if field_name not in payload:
                raise PolygonMalformedPayloadError(f"bar result is missing {field_name}")

        return cls(
            ticker=ticker,
            bar_date=bar_date,
            open=float(payload["o"]),
            high=float(payload["h"]),
            low=float(payload["l"]),
            close=float(payload["c"]),
            volume=int(payload.get("v", 0)),
            vwap=_optional_float(payload, "vw"),
            transactions=_optional_int(payload, "n"),
            raw=dict(payload),
        )


@dataclass(frozen=True)
class AggregatesPage:
    """Response from Polygon /v2/aggs/ticker/{ticker}/range/1/day endpoint."""

    ticker: str
    results: tuple[AggregateBar, ...]
    results_count: int
    query_count: int
    request_id: str | None = None
    status: str | None = None
    adjusted: bool = False
    next_url: str | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_payload(
        cls,
        payload: JsonObject,
        *,
        ticker: str,
        fetched_at: datetime | None = None,
    ) -> "AggregatesPage":
        if not isinstance(payload, dict):
            raise PolygonMalformedPayloadError("aggregates payload must be an object")

        results_payload = payload.get("results")
        if results_payload is None:
            results_payload = []
        if not isinstance(results_payload, list):
            raise PolygonMalformedPayloadError("aggregates results must be a list")

        results = tuple(
            AggregateBar.from_payload(item, ticker=ticker)
            for item in results_payload
        )

        return cls(
            ticker=ticker,
            results=results,
            results_count=payload.get("resultsCount", len(results)),
            query_count=payload.get("queryCount", 0),
            request_id=_optional_str(payload, "request_id"),
            status=_optional_str(payload, "status"),
            adjusted=payload.get("adjusted", False),
            next_url=_optional_str(payload, "next_url"),
            fetched_at=fetched_at or datetime.now(timezone.utc),
        )


def _optional_str(payload: JsonObject, key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _optional_float(payload: JsonObject, key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(payload: JsonObject, key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
