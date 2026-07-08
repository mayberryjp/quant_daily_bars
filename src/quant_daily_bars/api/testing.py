"""Thin WSGI test-client wrapper matching the quant_symbols TestClient interface."""

from __future__ import annotations

from webtest import TestApp


class _Response:
    """Adapter so callers can use ``response.status_code`` and ``response.json()``."""

    __slots__ = ("_resp", "status_code")

    def __init__(self, webtest_response):
        self._resp = webtest_response
        self.status_code = webtest_response.status_int

    def json(self):
        return self._resp.json


class WSGIClient:
    """Drop-in replacement for ``fastapi.testclient.TestClient``."""

    __test__ = False  # prevent pytest collection

    def __init__(self, app):
        self._app = TestApp(app)

    def get(self, url: str, *, params=None):
        resp = self._app.get(url, params=params, expect_errors=True)
        return _Response(resp)

    def post(self, url: str, *, json=None, params=None):
        if json is not None:
            resp = self._app.post_json(url, params=json, expect_errors=True)
        else:
            resp = self._app.post(url, params=params or {}, expect_errors=True)
        return _Response(resp)


# Alias used by all test files.
TestClient = WSGIClient
