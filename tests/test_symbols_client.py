"""Tests for the quant_symbols HTTP API client (no network required)."""

import pytest

from quant_daily_bars.symbols import client as client_module
from quant_daily_bars.symbols.client import Symbol, SymbolsApiClient, SymbolsApiError


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, handler):
        self._handler = handler
        self.requests = []

    def get(self, url, params=None, timeout=None):
        self.requests.append((url, params))
        return self._handler(url, params)


def _symbol_payload(symbol_id, ticker, active=True):
    return {"id": symbol_id, "canonical_ticker": ticker, "active": active}


class TestListActiveSymbols:
    def test_paginates_until_short_page(self, monkeypatch):
        monkeypatch.setattr(client_module, "_PAGE_LIMIT", 2)
        pages = {
            0: [_symbol_payload(1, "AAPL"), _symbol_payload(2, "MSFT")],
            2: [_symbol_payload(3, "NVDA")],
        }

        def handler(url, params):
            assert url.endswith("/symbols")
            assert params["active"] == "true"
            return _FakeResponse(200, {"items": pages.get(params["offset"], [])})

        session = _FakeSession(handler)
        client = SymbolsApiClient("http://symbols.test", session=session)

        symbols = client.list_active_symbols()

        assert symbols == [
            Symbol(symbol_id=1, ticker="AAPL", active=True),
            Symbol(symbol_id=2, ticker="MSFT", active=True),
            Symbol(symbol_id=3, ticker="NVDA", active=True),
        ]
        assert [params["offset"] for _, params in session.requests] == [0, 2]

    def test_non_200_raises(self):
        session = _FakeSession(lambda url, params: _FakeResponse(503, {}))
        client = SymbolsApiClient("http://symbols.test", session=session)
        with pytest.raises(SymbolsApiError):
            client.list_active_symbols()

    def test_network_failure_raises(self):
        def handler(url, params):
            raise ConnectionError("boom")

        client = SymbolsApiClient("http://symbols.test", session=_FakeSession(handler))
        with pytest.raises(SymbolsApiError):
            client.list_active_symbols()


class TestGetSymbolByTicker:
    def test_found(self):
        def handler(url, params):
            assert url.endswith("/symbols/by-ticker/AAPL")
            return _FakeResponse(200, _symbol_payload(42, "AAPL"))

        client = SymbolsApiClient("http://symbols.test", session=_FakeSession(handler))
        assert client.get_symbol_by_ticker("AAPL", active=True) == Symbol(42, "AAPL", True)

    def test_not_found_returns_none(self):
        client = SymbolsApiClient(
            "http://symbols.test",
            session=_FakeSession(lambda url, params: _FakeResponse(404, {"status": "not_found"})),
        )
        assert client.get_symbol_by_ticker("NOPE", active=True) is None

    def test_active_none_falls_back_to_inactive(self):
        def handler(url, params):
            if params["active"] == "true":
                return _FakeResponse(404, {"status": "not_found"})
            return _FakeResponse(200, _symbol_payload(9, "OLDCO", active=False))

        session = _FakeSession(handler)
        client = SymbolsApiClient("http://symbols.test", session=session)

        symbol = client.get_symbol_by_ticker("OLDCO")

        assert symbol == Symbol(9, "OLDCO", False)
        assert [params["active"] for _, params in session.requests] == ["true", "false"]
