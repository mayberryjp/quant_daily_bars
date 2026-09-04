"""HTTP client for the quant_symbols service.

The daily-bars service does not own the symbol universe. Symbols live in the
separate quant_symbols service, so we resolve them over its HTTP API instead of
joining across database schemas. Configure the base URL with ``SYMBOLS_API_URL``.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import quote, urljoin

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 30.0
# Largest page the quant_symbols /symbols endpoint allows.
_PAGE_LIMIT = 500


class SymbolsApiError(RuntimeError):
    """Raised when the quant_symbols API is unreachable or returns an error."""


@dataclass(frozen=True)
class Symbol:
    """A symbol resolved from the quant_symbols service."""

    symbol_id: int
    ticker: str
    active: bool

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Symbol":
        return cls(
            symbol_id=int(payload["id"]),
            ticker=payload["canonical_ticker"],
            active=bool(payload.get("active", True)),
        )


class SymbolsApiClient:
    """Thin, read-only HTTP client for the quant_symbols service."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        session: Any | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout = timeout
        if session is None:
            import requests

            session = requests.Session()
        self._session = session

    @classmethod
    def from_env(cls) -> "SymbolsApiClient":
        base_url = os.environ.get("SYMBOLS_API_URL", DEFAULT_BASE_URL)
        try:
            timeout = float(os.environ.get("SYMBOLS_API_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
        except ValueError:
            timeout = DEFAULT_TIMEOUT_SECONDS
        return cls(base_url, timeout=timeout)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = urljoin(self._base_url, path.lstrip("/"))
        try:
            return self._session.get(url, params=params, timeout=self._timeout)
        except Exception as exc:  # network / connection failures
            raise SymbolsApiError(f"symbols API request failed: GET {url}: {exc}") from exc

    def list_active_symbols(self) -> list[Symbol]:
        """Return every active symbol, paging through ``GET /symbols``."""
        return list(self._iter_symbols(active=True))

    def _iter_symbols(self, *, active: bool) -> Iterator[Symbol]:
        offset = 0
        while True:
            resp = self._get(
                "symbols",
                {"active": "true" if active else "false", "limit": _PAGE_LIMIT, "offset": offset},
            )
            if resp.status_code != 200:
                raise SymbolsApiError(f"symbols API returned HTTP {resp.status_code} for GET /symbols")
            items = resp.json().get("items", [])
            for item in items:
                yield Symbol.from_payload(item)
            if len(items) < _PAGE_LIMIT:
                return
            offset += _PAGE_LIMIT

    def get_symbol_by_ticker(self, ticker: str, *, active: bool | None = None) -> Symbol | None:
        """Look up one symbol by canonical ticker, or ``None`` if not found.

        ``active=None`` searches active symbols first and then inactive ones,
        matching the previous "any status" database lookup.
        """
        if active is None:
            return self.get_symbol_by_ticker(ticker, active=True) or self.get_symbol_by_ticker(
                ticker, active=False
            )
        resp = self._get(
            f"symbols/by-ticker/{quote(ticker, safe='')}",
            {"active": "true" if active else "false"},
        )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise SymbolsApiError(
                f"symbols API returned HTTP {resp.status_code} for GET /symbols/by-ticker/{ticker}"
            )
        return Symbol.from_payload(resp.json())
