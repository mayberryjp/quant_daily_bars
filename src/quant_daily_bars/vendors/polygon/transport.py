"""HTTP transport abstraction for Polygon vendor client."""

from __future__ import annotations

import ssl
import threading
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
import json

import requests
from requests.adapters import HTTPAdapter

from quant_daily_bars.vendors.polygon.errors import PolygonTimeoutError, PolygonTransportError


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> TransportResponse: ...


class UrllibTransport:
    """Default transport using urllib."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> TransportResponse:
        req = urllib.request.Request(url, method=method)
        if headers:
            for key, value in headers.items():
                req.add_header(key, value)
        try:
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                body = resp.read()
                resp_headers = {k: v for k, v in resp.headers.items()}
                return TransportResponse(
                    status_code=resp.status,
                    headers=resp_headers,
                    body=body,
                )
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read() if exc.fp else b""
                resp_headers = {k: v for k, v in exc.headers.items()} if exc.headers else {}
                return TransportResponse(
                    status_code=exc.code,
                    headers=resp_headers,
                    body=body,
                )
            finally:
                exc.close()
        except urllib.error.URLError as exc:
            if "timed out" in str(exc.reason):
                raise PolygonTimeoutError(f"request timed out: {exc}") from exc
            raise PolygonTransportError(f"transport error: {exc}") from exc
        except TimeoutError as exc:
            raise PolygonTimeoutError(f"request timed out: {exc}") from exc


class RequestsTransport:
    """HTTP transport with a persistent connection pool per worker thread."""

    def __init__(self, *, pool_size: int = 25) -> None:
        self._pool_size = pool_size
        self._local = threading.local()

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=self._pool_size,
                pool_maxsize=self._pool_size,
                pool_block=True,
            )
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            self._local.session = session
        return session

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> TransportResponse:
        try:
            response = self._session().request(
                method,
                url,
                headers=dict(headers) if headers else None,
                timeout=timeout,
            )
        except requests.Timeout as exc:
            raise PolygonTimeoutError(f"request timed out: {exc}") from exc
        except requests.RequestException as exc:
            raise PolygonTransportError(f"transport error: {exc}") from exc

        return TransportResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=response.content,
        )


def decode_json_body(response: TransportResponse) -> dict[str, Any]:
    return json.loads(response.body)
