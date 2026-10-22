"""Browser reader (Accela) parsing on a recorded Clark County results page. The browser
driver itself needs Chromium and a live portal, so it is not exercised offline."""
from __future__ import annotations

from supply_pipeline.readers import accela
from supply_pipeline.readers.entitlement import upsert_cases
from tests.fakes import fixture_bytes

HTML = fixture_bytes("accela/clark_tentative_map_results.html").decode()


def test_grid_rows_by_header_and_no_pager_row():
    rows = accela.parse_results_html(HTML)
    assert [r["record_number"] for r in rows] == ["26-500141", "26-500139", "26-500138", "26-500137"]
    assert rows[0]["project_type"].startswith("Residential - Development")
    assert rows[0]["applied_date_raw"] == "10/05/2026"
    assert all("prev" not in r["record_number"].lower() for r in rows)


def test_state_and_pagination():
    assert accela.results_state(HTML) == "rows"
    assert accela.has_next_link(HTML)
    detail = '<span id="ctl00_PlaceHolderMain_lblPermitNumber">26-500141</span><div>No records found.</div>'
    assert accela.results_state(detail) == "detail"
    assert accela.results_state("<div>No records found.</div>") == "empty"


def test_cases_and_storage(store):
    cases = [accela.to_case(r, "Tentative Map") for r in accela.parse_results_html(HTML)]
    assert all(c["stage"] == "plat" and c["county"] == "CLARK" for c in cases)
    c = cases[2]
    assert c["address"] == "84 Clearview Ridge RD LAS VEGAS, NV 89141"      # "Secondary" suffix stripped
    assert c["application_date"] == "2026-09-28"
    assert upsert_cases(store, cases) == 4


def test_pager_junk_and_prefix_stage():
    assert accela.to_case({"record_number": "< Prev"}, "Land Use") is None
    assert accela.to_case({"record_number": "2"}, "Land Use") is None
    assert accela.to_case({"record_number": "ZC-24-0123"}, "Land Use")["stage"] == "rezoning"
    assert accela.to_case({"record_number": "UC-25-0826"}, "Land Use")["stage"] == "use_permit"


def test_windows_cover_the_range_without_overlap():
    w = list(accela.windows("2026-01-01", "2026-12-31"))
    assert w[0] == ("2026-01-01", "2026-07-02") and w[-1][1] == "2026-12-31" and len(w) == 2


def test_dwelling_and_lifecycle():
    assert accela.dwelling("Apartment complex") == "multifamily"
    assert accela.dwelling("Residential Subdivision") == "single_family"
    assert accela.lifecycle("Denied") == "terminal" and accela.lifecycle("Approved") == "approved"
