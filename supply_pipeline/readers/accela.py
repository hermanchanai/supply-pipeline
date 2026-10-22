"""Method: browser automation. Accela Citizen Access portals render their search form and
results grid client-side, so a plain HTTP client sees neither; a headless browser drives
the form. Slowest and most fragile of the eight methods, so it is the last resort.

One engine, many tenants: an AccelaTenant is configuration (tenant id, module, record
types). Anonymous tenants only; this repo carries no login flow. Clark County, NV planning
cases are the bundled config.

The browser only drives: select a record type, fill a date window, click Search, click
Next. Every results page is handed to `parse_results_html`, plain Python over the page's
HTML, which is what the offline tests exercise against a recorded page.

What can go wrong, and what the engine does:
  * the date inputs are masked fields pre-filled with a default; typing appends to it.
    Set the value directly, fire the events, read it back, and fall back to keystrokes.
  * a search that matches exactly one record redirects to that record's detail page,
    which lacks the list columns. Re-run the search from an earlier start date until the
    list comes back and keep the one row.
  * the grid's pager bar is a nested table whose cells parse like a record ("< Prev").
    Only the grid's own rows count, and the case-number guard drops pager junk.
  * a Next click that does not change the first row, a results page that never renders,
    or max_pages with a Next link left: the search is recorded INCOMPLETE, never as done.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from .base import ReaderResult
from .entitlement import upsert_cases

log = logging.getLogger(__name__)

METHOD = "browser"
EXAMPLE_FEED = 193   # Las Vegas: Clark County Accela planning cases


@dataclass(frozen=True)
class AccelaTenant:
    tenant_id: str
    module: str
    label: str = ""
    base_url: str = "https://aca-prod.accela.com"

    @property
    def cap_home(self) -> str:
        return f"{self.base_url}/{self.tenant_id}/Cap/CapHome.aspx?module={self.module}&TabName={self.module}"

    def cap_detail_url(self, cap_id: str) -> str:
        return f"{self.base_url}/{self.tenant_id}/Cap/CapDetail.aspx?Module={self.module}&capID={cap_id}"


@dataclass
class SearchLog:
    """Searches that did not finish. A non-empty log means the run is incomplete."""
    incomplete: list[str] = field(default_factory=list)

    def record(self, why: str) -> None:
        log.warning("incomplete: %s", why)
        self.incomplete.append(why)


# --------------------------------------------------------------------------- Clark County
CLARK = AccelaTenant(tenant_id="CLARKCO", module="Planning", label="Clark County, NV: Comprehensive Planning")
RECORD_TYPES = ("Tentative Map", "Land Use", "Pre-Submittal", "Development Agreement", "Major Project",
                "Comprehensive Plan Amendment")
RT_STAGE = {"Tentative Map": "plat", "Land Use": "use_permit", "Pre-Submittal": "pre_application",
            "Development Agreement": "development_agreement", "Major Project": "dev_project",
            "Comprehensive Plan Amendment": "gpa"}
# Case numbers share the county scheme (UC-25-0826 / ZC-24-0123): the prefix refines "Land Use".
PREFIX_STAGE = {"ZC": "rezoning", "NZC": "rezoning", "TM": "plat", "UC": "use_permit", "SUP": "sup",
                "DR": "design_review", "GPA": "gpa", "WS": "variance", "WC": "variance", "VS": "abandonment",
                "ET": "use_permit", "PA": "pre_application", "DA": "development_agreement", "MP": "dev_project"}
_PREFIX_RE = re.compile(r"^([A-Z]{2,3})-\d{2}-\d{3,6}")
_MF_RE = re.compile(r"multi[- ]?family|apartment|condominium|\bcondo\b|mixed[- ]?use|"
                    r"senior (?:living|housing|apartments)|\bR-?[345]\b|\bRUD\b", re.I)
_TH_RE = re.compile(r"town ?home|town ?house", re.I)
_SF_RE = re.compile(r"single[- ]?family|\bsfr\b|residential subdivision", re.I)
_APPROVED = re.compile(r"approv|complete|closed|final|record", re.I)
_TERMINAL = re.compile(r"deni|withdraw|void|expire|cancel", re.I)


def dwelling(text: str) -> str:
    if _MF_RE.search(text):
        return "multifamily"
    if _TH_RE.search(text):
        return "townhome"
    if _SF_RE.search(text):
        return "single_family"
    return "unknown"


def lifecycle(status: str | None) -> str:
    s = status or ""
    return "terminal" if _TERMINAL.search(s) else "approved" if _APPROVED.search(s) else "in_review"


def windows(start_iso: str, end_iso: str, max_days: int = 183) -> Iterator[tuple[str, str]]:
    s, e = dt.date.fromisoformat(start_iso), dt.date.fromisoformat(end_iso)
    while s <= e:
        chunk = min(s + dt.timedelta(days=max_days - 1), e)
        yield s.isoformat(), chunk.isoformat()
        s = chunk + dt.timedelta(days=1)


def parse_date(raw: str | None) -> str | None:
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime((raw or "").strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def to_case(row: dict, record_type: str, tenant: AccelaTenant = CLARK) -> dict | None:
    case_no = (row.get("record_number") or "").strip()
    # pager-bar guard: "< Prev" / bare page digits parse as a record number
    if len(case_no) < 5 or not re.search(r"\d{2,}", case_no) or re.search(r"prev|next", case_no, re.I):
        return None
    stage = RT_STAGE.get(record_type, "use_permit")
    pm = _PREFIX_RE.match(case_no)
    if record_type == "Land Use" and pm:
        stage = PREFIX_STAGE.get(pm.group(1), stage)
    project_type = (row.get("project_type") or "").strip() or None
    name = (row.get("project_name") or "").strip() or None
    notes = (row.get("short_notes") or "").strip() or None
    addr = re.sub(r"\s*(Secondary|Primary)\s*$", "", (row.get("site_address") or "").strip()).strip() or None
    status = (row.get("status") or "").strip() or None
    applied = parse_date(row.get("applied_date_raw"))
    return {
        "msa": "las_vegas", "jurisdiction": "clark_accela_planning", "source_type": "accela_planning",
        "case_number": case_no, "case_type_raw": row.get("record_type") or record_type, "stage": stage,
        "project_name": name, "status_raw": status, "lifecycle_status": lifecycle(status),
        "application_date": applied, "latest_action_date": applied, "land_use_raw": project_type,
        "dwelling_type": dwelling(f"{name or ''} {notes or ''} {project_type or ''}"),
        "address": addr, "county": "CLARK", "latitude": None, "longitude": None,
        "link": tenant.cap_detail_url(case_no),
        "raw_json": {k: v for k, v in row.items() if v not in (None, "")},
    }


# --------------------------------------------------------------------------- page parsing
def header_to_key(h: str) -> str:
    s = re.sub(r"\s+", "_", re.sub(r"[^A-Za-z0-9 ]", "", h or "").strip().lower())
    return {
        "": "site_address", "date": "applied_date_raw", "record_number": "record_number",
        "permit_number": "record_number", "permits_number": "record_number",
        "recordapplication_number": "record_number", "record_type": "record_type",
        "permit_type": "record_type", "permits_type": "record_type", "recordapplication_type": "record_type",
        "application_name": "project_name", "project_name": "project_name", "project_type": "project_type",
        "description": "short_notes", "short_notes": "short_notes", "address": "site_address",
        "status": "status", "action": "action",
    }.get(s, s or "site_address")


def parse_results_html(html: str) -> list[dict]:
    """Rows of the results grid as dicts keyed by normalized header. Only the grid's own
    rows count: the pager is a nested table whose row would otherwise read as a record."""
    soup = BeautifulSoup(html, "html.parser")
    grid = soup.select_one("table[id*='PermitList']")
    if grid is None:
        return []
    keys = [header_to_key(th.get_text(" ", strip=True)) for th in grid.find_all("th")]
    out = []
    for tr in grid.find_all("tr"):
        if tr.find_parent("table") is not grid:
            continue
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 5:
            continue
        cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in tds]
        row = dict(zip(keys, cells, strict=False))
        if row.get("record_number"):
            out.append(row)
    return out


def results_state(html: str, url: str = "") -> str:
    """'rows' | 'detail' (single-match redirect) | 'empty'. The detail check runs first:
    a detail page has a "No records found." cell of its own (an empty inspections list)."""
    soup = BeautifulSoup(html, "html.parser")
    if "/Cap/CapDetail.aspx" in url or soup.select_one("span[id$='PlaceHolderMain_lblPermitNumber']"):
        return "detail"
    if soup.select_one("table[id*='PermitList']"):
        return "rows"
    return "empty"


def has_next_link(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return any(re.match(r"^next\b", a.get_text(strip=True), re.I) for a in soup.find_all("a"))


# --------------------------------------------------------------------------- browser driver
_SET_DATE_JS = """(e, v) => { e.focus(); e.value = v;
  e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true}));
  e.blur(); }"""
_FIRST_ROW_JS = """() => { const t = document.querySelector("table[id*='PermitList']"); if (!t) return null;
  for (const tr of t.querySelectorAll('tr')) { const tds = tr.querySelectorAll(':scope > td');
    if (tds.length >= 5) return Array.from(tds).map(td => (td.innerText || '').trim()).join('|'); }
  return null; }"""


def _settle(page, ms: int = 10_000) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=ms)
    except Exception:   # a slow settle is not a failure
        pass


def _set_dates(page, start_iso: str, end_iso: str) -> None:
    fields = (("input[id*='txtGSStartDate']", dt.date.fromisoformat(start_iso).strftime("%m/%d/%Y")),
              ("input[id*='txtGSEndDate']", dt.date.fromisoformat(end_iso).strftime("%m/%d/%Y")))
    for setter in ("js", "typed"):
        for sel, want in fields:
            if setter == "js":
                page.eval_on_selector(sel, _SET_DATE_JS, want)
            else:
                page.click(sel)
                page.keyboard.press("End")
                for _ in range(len(page.eval_on_selector(sel, "e => e.value") or "") + 2):
                    page.keyboard.press("Backspace")
                page.keyboard.type(want, delay=30)
                page.keyboard.press("Tab")
        _settle(page, 8_000)
        if all(parse_date(page.eval_on_selector(sel, "e => e.value")) == parse_date(want) for sel, want in fields):
            return
    raise RuntimeError("date window did not take; refusing to search an unknown window")


def search(page, tenant: AccelaTenant, *, start_date: str, end_date: str, record_type: str,
           slog: SearchLog, max_pages: int = 120, _recovering: bool = False) -> Iterator[dict]:
    """One search; yields one row dict per result across all pages."""
    page.goto(tenant.cap_home, wait_until="domcontentloaded")
    _settle(page, 20_000)
    page.select_option("select[id*='ddlGSPermitType']", label=record_type)
    _settle(page)
    page.evaluate("() => new Promise(r => setTimeout(r, 800))")   # flush the dropdown's postback
    _set_dates(page, start_date, end_date)
    page.eval_on_selector("a[id*='btnNewSearch']", "e => e.click()")   # a JS click: a mask covers the button
    try:
        page.wait_for_selector("table[id*='PermitList'], span[id$='PlaceHolderMain_lblPermitNumber'], "
                               "div:has-text('No records found')", timeout=30_000, state="attached")
    except Exception:
        slog.record(f"{tenant.tenant_id} {record_type!r} {start_date}..{end_date}: results never rendered")
        return
    state = results_state(page.content(), page.url)
    if state == "empty":
        return
    if state == "detail":
        yield from _recover_single_match(page, tenant, start_date=start_date, end_date=end_date,
                                         record_type=record_type, slog=slog, recovering=_recovering)
        return
    seen: set[str] = set()
    for page_idx in range(1, max_pages + 1):
        html = page.content()
        new = [r for r in parse_results_html(html) if r["record_number"] not in seen]
        if not new and page_idx > 1:
            return
        for r in new:
            seen.add(r["record_number"])
            yield r
        if not has_next_link(html):
            return
        before = page.evaluate(_FIRST_ROW_JS)
        page.evaluate("""() => { const a = Array.from(document.querySelectorAll('a'))
            .find(x => /^next\\b/i.test((x.textContent || '').trim())); if (a) a.click(); }""")
        try:
            page.wait_for_function(f"(b) => {{ const s = ({_FIRST_ROW_JS})(); return s !== null && s !== b; }}",
                                   arg=before, timeout=30_000)
        except Exception:
            slog.record(f"{tenant.tenant_id} {record_type!r} {start_date}..{end_date}: "
                        f"Next on page {page_idx} did not advance")
            return
    slog.record(f"{tenant.tenant_id} {record_type!r} {start_date}..{end_date}: stopped at max_pages={max_pages}")


def _recover_single_match(page, tenant, *, start_date, end_date, record_type, slog, recovering):
    """A single match redirects to its detail page. Widen the window backwards until the
    search returns a list, then keep only the record that matched."""
    rn = (page.inner_text("span[id$='PlaceHolderMain_lblPermitNumber']") or "").strip()
    if recovering:
        return
    start = dt.date.fromisoformat(start_date)
    for years in (5, 15):
        wider = start.replace(year=start.year - years, day=min(start.day, 28)).isoformat()
        for row in search(page, tenant, start_date=wider, end_date=end_date, record_type=record_type,
                          slog=slog, _recovering=True):
            if row.get("record_number") == rn:
                yield row
                return
    slog.record(f"{tenant.tenant_id} {record_type!r} {start_date}..{end_date}: single match {rn} not recovered")


def run(store, *, start_date: str | None = None, end_date: str | None = None, tenant: AccelaTenant = CLARK,
        record_types: tuple[str, ...] = RECORD_TYPES, headed: bool = False) -> ReaderResult:
    from playwright.sync_api import sync_playwright  # requirements-live.txt
    end_date = end_date or dt.date.today().isoformat()
    start_date = start_date or (dt.date.fromisoformat(end_date) - dt.timedelta(days=30)).isoformat()
    slog, rows, fetched = SearchLog(), {}, 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        try:
            for rt in record_types:
                for w0, w1 in windows(start_date, end_date):
                    ctx = browser.new_context(viewport={"width": 1366, "height": 900})
                    ctx.route(re.compile(r"\.(png|jpe?g|gif|svg|woff2?|ttf|ico)(\?|$)", re.I),
                              lambda route: route.abort())
                    try:
                        for raw in search(ctx.new_page(), tenant, start_date=w0, end_date=w1,
                                          record_type=rt, slog=slog):
                            fetched += 1
                            case = to_case(raw, rt, tenant)
                            if case:
                                rows[case["case_number"]] = case
                    except Exception as e:   # one failed window is recorded, the rest still run
                        slog.record(f"{rt!r} {w0}..{w1}: {type(e).__name__}: {e}"[:200])
                    finally:
                        ctx.close()
        finally:
            browser.close()
    n = upsert_cases(store, list(rows.values()))
    return ReaderResult("clark_accela_planning", fetched, n, notes={"incomplete": slog.incomplete})
