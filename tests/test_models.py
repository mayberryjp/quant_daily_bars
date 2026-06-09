"""Tests for Polygon daily bars response model parsing."""

from datetime import date, datetime, timezone

from quant_daily_bars.vendors.polygon.models import AggregateBar, AggregatesPage


def _sample_bar_payload() -> dict:
    return {
        "v": 82034459,
        "vw": 186.2453,
        "o": 187.15,
        "c": 185.56,
        "h": 187.44,
        "l": 185.19,
        "t": 1704067200000,  # 2024-01-01 UTC
        "n": 682721,
    }


def _sample_page_payload() -> dict:
    return {
        "ticker": "AAPL",
        "queryCount": 1,
        "resultsCount": 1,
        "adjusted": False,
        "results": [_sample_bar_payload()],
        "status": "OK",
        "request_id": "test-req-1",
    }


class TestAggregateBar:
    def test_from_payload(self):
        bar = AggregateBar.from_payload(_sample_bar_payload(), ticker="AAPL")
        assert bar.ticker == "AAPL"
        assert bar.bar_date == date(2024, 1, 1)
        assert bar.open == 187.15
        assert bar.high == 187.44
        assert bar.low == 185.19
        assert bar.close == 185.56
        assert bar.volume == 82034459
        assert bar.vwap == 186.2453
        assert bar.transactions == 682721

    def test_missing_timestamp_raises(self):
        payload = _sample_bar_payload()
        del payload["t"]
        try:
            AggregateBar.from_payload(payload, ticker="AAPL")
            assert False, "should have raised"
        except Exception as exc:
            assert "timestamp" in str(exc).lower()

    def test_missing_ohlc_raises(self):
        for field in ("o", "h", "l", "c"):
            payload = _sample_bar_payload()
            del payload[field]
            try:
                AggregateBar.from_payload(payload, ticker="AAPL")
                assert False, f"should have raised for missing {field}"
            except Exception:
                pass


class TestAggregatesPage:
    def test_from_payload(self):
        page = AggregatesPage.from_payload(_sample_page_payload(), ticker="AAPL")
        assert page.ticker == "AAPL"
        assert len(page.results) == 1
        assert page.results[0].close == 185.56
        assert page.status == "OK"
        assert page.adjusted is False

    def test_empty_results(self):
        payload = _sample_page_payload()
        payload["results"] = []
        payload["resultsCount"] = 0
        page = AggregatesPage.from_payload(payload, ticker="AAPL")
        assert len(page.results) == 0

    def test_missing_results_key_defaults_empty(self):
        payload = _sample_page_payload()
        del payload["results"]
        page = AggregatesPage.from_payload(payload, ticker="AAPL")
        assert len(page.results) == 0
