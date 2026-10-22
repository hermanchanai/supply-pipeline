"""Method: HTML page scrape. TCEQ's water-quality permit search (a ColdFusion app) for
construction stormwater notices of intent, TXR150000.

Mechanics:
  1. POST the search criteria with a cookie jar -> page 1 and a result-count message
  2. GET ?CurrentPage=N&fuseaction=home.permit_list (same cookies) -> page N
  3. GET the per-NOI summary page -> site name, status, dates, acres, construction type, lat/lon

Two server rules that are easy to refactor away by accident:
  * the submit fuseaction is `home.validate_search_crit`;
  * never send permit_status and app_status together (the validator rejects the search).

The list table is parsed by its header row, so a redesign that inserts or moves a column
does not shift every value one place over. Dwelling type comes from the rule layer in
tceq_rules.py, with a language model only for the rows the rules cannot decide.
"""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from .. import http
from .base import ReaderResult

log = logging.getLogger(__name__)

METHOD = "html_scrape"
EXAMPLE_FEED = 18   # Houston: TCEQ CGP NOI (TXR150000), region 12

BASE_URL = "https://www2.tceq.texas.gov/wq_dpa/index.cfm"
METRO_COUNTIES = {
    "houston": ["HARRIS", "FORT BEND", "MONTGOMERY", "BRAZORIA", "GALVESTON", "WALLER", "LIBERTY",
                "CHAMBERS", "AUSTIN"],
    "austin": ["TRAVIS", "WILLIAMSON", "HAYS", "BASTROP", "CALDWELL"],
}
PAGE_ROWS = 50
_RESULT_COUNT_RE = re.compile(r"returned\s+(\d+)\s+records", re.I)
_DISTINCT_RE = re.compile(r"distinct permits found is\s+(\d+)", re.I)
_DATE_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")


def submit_search(session, county: str, status: str, start: str, end: str) -> str:
    """POST the advanced search (dates MM/DD/YYYY). Returns page-1 HTML."""
    form = {
        "fuseaction": "home.validate_search_crit", "newsearch": "yes", "goto": "search",
        "permit_type": "SWC|Construction Notice of Intent (TXR15)",
        "permit_status": status,   # never together with app_status
        "cnty_name": county.upper(), "start_date": start, "end_date": end,
        "permitStatusList": "ACTIVE,DENIED,EXPIRED,TERMINATED,WITHDRAWN",
        "appStatusList": "APPROVED,PENDING,DENIED,WITHDRAWN",
    }
    r = session.post(BASE_URL, data=form, timeout=60)
    r.raise_for_status()
    return r.text


def fetch_list_page(session, page: int) -> str:
    r = session.get(BASE_URL, params={"CurrentPage": page, "fuseaction": "home.permit_list",
                                      "sort": "lgl_ident_txt"}, timeout=60)
    r.raise_for_status()
    return r.text


def parse_total_count(html: str) -> tuple[int, int]:
    """(total list rows, distinct permits)."""
    total = int(m.group(1)) if (m := _RESULT_COUNT_RE.search(html)) else 0
    distinct = int(m.group(1)) if (m := _DISTINCT_RE.search(html)) else 0
    return total, distinct


def _header_map(soup) -> dict[str, int]:
    for tr in soup.find_all("tr"):
        ths = tr.find_all("th")
        texts = [th.get_text(" ", strip=True).lower() for th in ths]
        if texts and any("auth" in t for t in texts) and any("county" in t for t in texts):
            return {t: i for i, t in enumerate(texts)}
    return {}


def parse_list_rows(html: str) -> list[dict]:
    """One row per summary link. The link URL carries every id the summary page needs;
    the cells carry the list fields, located by header text."""
    soup = BeautifulSoup(html, "html.parser")
    hmap = _header_map(soup)
    if not hmap:
        raise ValueError("TCEQ list page has no recognizable header row; layout changed?")
    rows = []
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=re.compile(r"fuseaction=home\.permit_summary"))
        if a is None:
            continue
        qs = parse_qs(urlparse(unquote(a["href"]).replace("&amp;", "&")).query)
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]

        def col(name: str, cells=cells) -> str | None:
            i = next((i for h, i in hmap.items() if h.startswith(name)), None)
            return (cells[i] or None) if i is not None and i < len(cells) else None

        region_number = col("region")
        rows.append({
            "authorization_number": (qs.get("lgl_ident_txt", [None])[0] or a.get_text(strip=True)),
            **{k: qs.get(k, [None])[0] for k in ("lgl_id", "pita_id", "phys_id", "princ_id", "reg_ent_id")},
            "affil_role": qs.get("affil_role", [None])[0],
            "permit_type_code": qs.get("permit_type_code", [None])[0],
            "project_name": col("site name"),
            "operator_name": col("permittee"),
            "primary_sic_code": col("sic"),
            "site_county": col("county"),
            "region_number": int(region_number) if (region_number or "").isdigit() else None,
            "site_city": col("city"),
            "site_address": col("site location"),
        })
    return rows


def detail_url(row: dict) -> str:
    params = {"fuseaction": "home.permit_summary", "lgl_ident_txt": row.get("authorization_number"),
              "lgl_id": row.get("lgl_id"), "pita_id": row.get("pita_id"), "phys_id": row.get("phys_id"),
              "princ_id": row.get("princ_id"), "affil_role": row.get("affil_role") or "2",
              "reg_ent_id": row.get("reg_ent_id"), "permit_type_code": row.get("permit_type_code") or "SWC",
              "return_to": "permit_list"}
    return BASE_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items() if v is not None)


def _norm_date(s: str | None) -> str | None:
    m = _DATE_RE.search(s or "")
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else None


def _to_bool(s: str | None) -> bool | None:
    s = (s or "").strip().upper()
    return True if s in {"YES", "Y", "TRUE", "1"} else False if s in {"NO", "N", "FALSE", "0"} else None


def _num(s) -> float | None:
    try:
        return float(str(s).replace(",", "").strip()) if s else None
    except ValueError:
        return None


def parse_detail_page(html: str) -> dict:
    """The summary page is a run of <p><label>X:</label>VALUE</p> blocks."""
    soup = BeautifulSoup(html, "html.parser")
    fields: dict[str, str | None] = {}
    for p in soup.find_all("p"):
        lab = p.find("label")
        if lab is None:
            continue
        label_text = lab.get_text(" ", strip=True)
        label = label_text.rstrip(":").strip()
        if not label:
            continue
        full = p.get_text(" ", strip=True)
        value = full[len(label_text):] if full.startswith(label_text) else full.split(label, 1)[-1]
        fields[label.lower()] = value.lstrip(": \t").strip() or None

    def f(*labels):
        return next((fields[k.lower()] for k in labels if fields.get(k.lower())), None)

    replaced = f("Replaced Permit Number")
    return {
        "project_name": f("Site Name on Permit"),
        "authorization_status": f("Authorization Status"),
        "authorization_type": f("Authorization Type"),
        "date_coverage_began": _norm_date(f("Date Coverage Began")),
        "date_coverage_ended": _norm_date(f("Date Coverage Ended")),
        "replaced_permit_number": replaced if replaced and replaced.lower() != "authorization details" else None,
        "disturbed_acres": _num(f("Area Disturbed (in Acres)", "Area Disturbed")),
        "common_plan_of_development": _to_bool(f("common plan of development")),
        "construction_type": f("construction type"),
        "latitude": _num(f("Latitude")),
        "longitude": _num(f("Longitude")),
    }


def scrape_county(session, county: str, start: str, end: str, *, status: str = "ALL",
                  details: bool = True, max_pages: int | None = None, throttle: float = 1.0) -> list[dict]:
    html = submit_search(session, county, status, start, end)
    total, distinct = parse_total_count(html)
    log.info("%s: %d list rows, %d distinct NOIs", county, total, distinct)
    rows, page = [], 1
    while True:
        if page > 1:
            html = fetch_list_page(session, page)
        page_rows = parse_list_rows(html)
        rows.extend(page_rows)
        if not page_rows or len(rows) >= total or len(page_rows) < PAGE_ROWS:
            break
        page += 1
        if max_pages and page > max_pages:
            break
    unique = list({r["authorization_number"]: r for r in rows if r["authorization_number"]}.values())
    if details:
        for r in unique:
            resp = session.get(detail_url(r), timeout=60)
            resp.raise_for_status()
            r.update({k: v for k, v in parse_detail_page(resp.text).items() if v is not None})
            time.sleep(throttle)
    return unique


def run(store, county: str = "HARRIS", start: str = "01/01/2020", end: str | None = None, *,
        session=None, details: bool = True, classify_rows: bool = True, throttle: float = 1.0) -> ReaderResult:
    from datetime import date

    from .tceq_rules import decide_rules
    session = session or http.session()
    end = end or date.today().strftime("%m/%d/%Y")
    rows = scrape_county(session, county, start, end, details=details, throttle=throttle)
    if classify_rows:
        for r in rows:
            label = decide_rules(r)
            if label:                      # undecided rows wait for the model pass
                r["dwelling_type"] = label
    for r in rows:   # url-only ids, not table columns
        r.pop("affil_role", None)
        r.pop("permit_type_code", None)
    n = store.upsert("tceq.cgp_noi", rows, key=("authorization_number",), coalesce=("dwelling_type",))
    return ReaderResult(f"tceq_{county.lower()}", len(rows), n,
                        notes={"rule_labelled": sum(1 for r in rows if r.get("dwelling_type"))})
