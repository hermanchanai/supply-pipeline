"""Method: open-data API. A Socrata (SODA) dataset with documented fields.

One generic reader; a dataset is configuration. The City of Austin subdivision cases
dataset ships (the example feed). Socrata returns every value as a string, including
numbers, so the transform casts locally.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .. import http
from .base import ReaderResult

log = logging.getLogger(__name__)

METHOD = "open_data_api"
EXAMPLE_FEED = 14   # Austin: City of Austin subdivision review cases


def to_int(v) -> int | None:
    if v in (None, "", "."):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def to_float(v) -> float | None:
    if v in (None, "", "."):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_date(v) -> str | None:
    return v[:10] if isinstance(v, str) and len(v) >= 10 else None


@dataclass(frozen=True)
class Dataset:
    name: str
    base: str
    dataset_id: str
    table: str
    key: str
    transform: Callable[[dict], dict | None]
    date_field: str | None = None
    page_size: int = 50_000


def austin_subdivision_case(r: dict) -> dict | None:
    """Applicant, case-manager and geometry fields are not read."""
    frsn = r.get("folderrsn")
    if not frsn:
        return None
    return {
        "folderrsn": str(frsn),
        "case_number": r.get("case_number"),
        "permit_number": r.get("permit_number"),
        "case_name": r.get("subdivision_case_name"),
        "case_type": r.get("case_type"),
        "sub_type": r.get("sub_type"),
        "case_status": r.get("subdivision_case_status"),
        "application_start_date": to_date(r.get("application_start_date")),
        "approval_date": to_date(r.get("approval_date")),
        "proposed_no_of_lots": to_int(r.get("proposed_no_of_lots")),
        "gross_site_area_acres": to_float(r.get("gross_site_area_acres")),
        "latitude": to_float(r.get("latitude")),
        "longitude": to_float(r.get("longitude")),
    }


AUSTIN_SUBDIVISIONS = Dataset(
    name="austin_subdivision_cases", base="https://data.austintexas.gov/resource",
    dataset_id="it4s-wgjk", table="coa.subdivision_review_cases", key="folderrsn",
    transform=austin_subdivision_case, date_field="application_start_date")


def fetch(session, ds: Dataset, since: str | None = None, limit: int | None = None) -> list[dict]:
    url = f"{ds.base}/{ds.dataset_id}.json"
    per_page = min(limit, ds.page_size) if limit else ds.page_size
    out: list[dict] = []
    offset = 0
    while True:
        params = {"$limit": per_page, "$offset": offset,
                  "$order": f"{ds.date_field} ASC" if (ds.date_field and since) else ":id"}
        if ds.date_field and since:
            params["$where"] = f"{ds.date_field} > '{since}'"
        r = session.get(url, params=params, timeout=120)
        r.raise_for_status()
        chunk = r.json()
        if not isinstance(chunk, list):
            raise RuntimeError(f"{ds.name}: Socrata error envelope {str(chunk)[:200]}")
        out.extend(chunk)
        log.info("%s: offset %d -> %d rows", ds.name, offset, len(chunk))
        if limit and len(out) >= limit:
            return out[:limit]
        if len(chunk) < per_page:
            return out
        offset += per_page


def run(store, ds: Dataset = AUSTIN_SUBDIVISIONS, *, since: str | None = None,
        limit: int | None = None, session=None) -> ReaderResult:
    session = session or http.session()
    raw = fetch(session, ds, since, limit)
    now = datetime.now(UTC)
    rows = [{**t, "last_refreshed_at": now} for t in (ds.transform(r) for r in raw) if t is not None]
    n = store.upsert(ds.table, rows, key=(ds.key,))
    return ReaderResult(ds.name, len(raw), n)
