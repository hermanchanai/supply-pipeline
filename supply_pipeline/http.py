"""One User-Agent and one session factory for every reader.

Readers take an optional `session` so tests can hand them a recorded-response fake;
nothing in the test suite opens a network socket.
"""
from __future__ import annotations

import requests

USER_AGENT = "supply-pipeline/1.0 (+https://hermanchan.ai)"


def session(extra_headers: dict | None = None) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, **(extra_headers or {})})
    return s
