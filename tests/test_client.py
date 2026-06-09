"""Tests for Polygon bars client with mocked transport."""

from dataclasses import dataclass
from datetime import date
import json

from quant_daily_bars.vendors.polygon.client import PolygonBarsClient
from quant_daily_bars.vendors.polygon.config import PolygonConfig
from quant_daily_bars.vendors.polygon.rate_limiter import SharedRateLimiter
from quant_daily_bars.vendors.polygon.transport import TransportResponse


@dataclass
class MockTransport:
    """Returns canned responses for testing."""

    responses: list[TransportResponse]
    _call_count: int = 0

    def request(self, method, url, *, headers=None, timeout=None):
        idx = min(self._call_count, len(self.responses) - 1)
        self._call_count += 1
        return self.responses[idx]


def _ok_response(payload: dict) -> TransportResponse:
    return TransportResponse(
        status_code=200,
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload).encode(),
    )


def _bar_payload(ticker="AAPL"):
    return {
        "ticker": ticker,
        "queryCount": 2,
        "resultsCount": 2,
        "adjusted": False,
        "results": [
            {"v": 100, "vw": 150.0, "o": 149.0, "c": 151.0, "h": 152.0, "l": 148.0, "t": 1704067200000, "n": 50},
            {"v": 200, "vw": 152.0, "o": 151.0, "c": 153.0, "h": 154.0, "l": 150.0, "t": 1704153600000, "n": 75},
        ],
        "status": "OK",
        "request_id": "test-1",
    }


class TestPolygonBarsClient:
    def _make_client(self, responses):
        config = PolygonConfig(api_key="test-key", rate_limit_rpm=0)
        transport = MockTransport(responses=responses)
        limiter = SharedRateLimiter(rpm=0)  # disable for unit tests
        return PolygonBarsClient(config, transport=transport, sleep=lambda _: None, rate_limiter=limiter)

    def test_get_daily_bars(self):
        client = self._make_client([_ok_response(_bar_payload())])
        page = client.get_daily_bars(
            ticker="AAPL",
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 5),
        )
        assert page.ticker == "AAPL"
        assert len(page.results) == 2
        assert page.results[0].open == 149.0
        assert page.results[1].close == 153.0

    def test_iter_daily_bars_single_page(self):
        client = self._make_client([_ok_response(_bar_payload())])
        pages = list(client.iter_daily_bars(
            ticker="AAPL",
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 5),
        ))
        assert len(pages) == 1
        assert len(pages[0].results) == 2

    def test_iter_daily_bars_pagination(self):
        page1 = _bar_payload()
        page1["next_url"] = "https://api.polygon.io/v2/aggs/next?cursor=abc"
        page2 = _bar_payload()
        # page2 has no next_url -> stops

        client = self._make_client([_ok_response(page1), _ok_response(page2)])
        pages = list(client.iter_daily_bars(
            ticker="AAPL",
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 5),
        ))
        assert len(pages) == 2

    def test_auth_error(self):
        error_resp = TransportResponse(
            status_code=401,
            headers={},
            body=json.dumps({"error": "unauthorized"}).encode(),
        )
        client = self._make_client([error_resp])
        try:
            client.get_daily_bars(ticker="AAPL", from_date=date(2024, 1, 1), to_date=date(2024, 1, 5))
            assert False, "should have raised"
        except Exception as exc:
            assert "authentication" in str(exc).lower()

    def test_rate_limit_retries(self):
        rate_resp = TransportResponse(
            status_code=429,
            headers={"Retry-After": "1"},
            body=b"{}",
        )
        ok_resp = _ok_response(_bar_payload())
        client = self._make_client([rate_resp, ok_resp])
        page = client.get_daily_bars(ticker="AAPL", from_date=date(2024, 1, 1), to_date=date(2024, 1, 5))
        assert len(page.results) == 2
