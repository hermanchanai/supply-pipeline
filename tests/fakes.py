"""Recorded-response stand-in for requests.Session. No socket is ever opened."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200, content_type: str = "application/json"):
        self.content = body
        self.status_code = status
        self.headers = {"content-type": content_type, "Content-Type": content_type}

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} Error")


@dataclass
class Route:
    method: str
    url_contains: str
    response: Callable[[dict], FakeResponse]
    when: Callable[[dict], bool] = lambda req: True


@dataclass
class RecordedSession:
    routes: list[Route] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    headers: dict = field(default_factory=dict)

    def add(self, method: str, url_contains: str, response, when=None) -> RecordedSession:
        fn = response if callable(response) else (lambda req, r=response: r)
        self.routes.append(Route(method.upper(), url_contains, fn, when or (lambda req: True)))
        return self

    def _dispatch(self, method: str, url: str, **kw) -> FakeResponse:
        req = {"method": method, "url": url, **kw}
        self.calls.append(req)
        for r in self.routes:
            if r.method == method and r.url_contains in url and r.when(req):
                return r.response(req)
        raise AssertionError(f"no recorded response for {method} {url} {kw.get('params') or ''}")

    def get(self, url, **kw):
        return self._dispatch("GET", url, **kw)

    def post(self, url, **kw):
        return self._dispatch("POST", url, **kw)


def fixture_bytes(rel: str) -> bytes:
    return (FIXTURES / rel).read_bytes()


def json_response(rel: str) -> FakeResponse:
    return FakeResponse(fixture_bytes(rel))


def html_response(rel: str) -> FakeResponse:
    return FakeResponse(fixture_bytes(rel), content_type="text/html; charset=utf-8")
