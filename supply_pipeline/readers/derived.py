"""Method: derived view. Not a download: a filtered view over a table another feed already
loads (schema/080_views.sql, `nashville.v_planning_entitlements`).

There is nothing to fetch. "Running" this feed means reading the view after the ArcGIS
reader has loaded planning cases, which is what the registry's coverage count does too.
"""
from __future__ import annotations

from .base import ReaderResult

METHOD = "derived"
EXAMPLE_FEED = 177   # Nashville: Davidson Metro planning entitlement arm
VIEW = "nashville.v_planning_entitlements"


def rows(store) -> list[dict]:
    return store.rows(f"SELECT * FROM {VIEW} ORDER BY case_number")


def run(store, **_) -> ReaderResult:
    n = store.rows(f"SELECT count(*) AS n FROM {VIEW}")[0]["n"]
    return ReaderResult("nashville_planning_entitlements", n, 0)
