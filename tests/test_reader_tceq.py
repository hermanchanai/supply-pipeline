"""HTML scrape reader (TCEQ) on recorded Waller County pages, plus the rule layer."""
from __future__ import annotations

import pytest

from supply_pipeline.readers import tceq
from supply_pipeline.readers.tceq_rules import decide_rules, mf_override
from tests.fakes import RecordedSession, fixture_bytes, html_response


def test_list_page_is_parsed_by_header():
    rows = tceq.parse_list_rows(fixture_bytes("tceq/waller_list_p1.html").decode())
    assert [r["authorization_number"] for r in rows][:2] == ["TXR1501ZP", "TXR1510ZI"]
    r = rows[0]
    assert (r["project_name"], r["operator_name"], r["primary_sic_code"], r["site_county"], r["region_number"]) == \
        ("FALCON MANOR SEC 1", "Bay Utilities, L.L.C.", "1623", "WALLER", 12)
    assert r["lgl_id"] == "33311584"


def test_a_page_without_the_header_row_raises():
    with pytest.raises(ValueError, match="header row"):
        tceq.parse_list_rows("<table><tr><td>TXR1</td></tr></table>")


def test_detail_page_fields():
    d = tceq.parse_detail_page(fixture_bytes("tceq/detail_TXR1501ZP.html").decode())
    assert d["construction_type"] == "SINGLE-FAMILY RESIDENTIAL"
    assert (d["disturbed_acres"], d["latitude"], d["longitude"]) == (18.24, 30.12, -95.84)
    assert (d["date_coverage_began"], d["date_coverage_ended"]) == ("2026-09-29", None)
    assert d["common_plan_of_development"] is False


def test_run_loads_rows_and_labels_what_the_rules_can(store):
    s = RecordedSession()
    s.add("POST", "wq_dpa/index.cfm", html_response("tceq/waller_list_p1.html"))
    s.add("GET", "lgl_ident_txt=TXR1501ZP", html_response("tceq/detail_TXR1501ZP.html"))
    s.add("GET", "permit_summary", html_response("tceq/detail_TXR1501ZP.html").__class__(b"<html></html>",
                                                                                     content_type="text/html"))
    res = tceq.run(store, "WALLER", "09/01/2026", "10/15/2026", session=s, throttle=0)
    assert s.calls[0]["data"]["fuseaction"] == "home.validate_search_crit"
    assert "app_status" not in s.calls[0]["data"]          # never with permit_status
    assert res.fetched == 5 and res.upserted == 5
    falcon = store.rows("select * from tceq.cgp_noi where authorization_number = 'TXR1501ZP'")[0]
    assert falcon["construction_type"] == "SINGLE-FAMILY RESIDENTIAL"
    assert falcon["dwelling_type"] == "single_family"      # subdivision name ("SEC 1") + CT


def row(name, op="", ct="COMMERCIAL", sic="1623", acres=None):
    return {"project_name": name, "operator_name": op, "construction_type": ct, "primary_sic_code": sic,
            "disturbed_acres": acres}


@pytest.mark.parametrize("r,expected", [
    (row("LAWHON MULTI FAMILY PHS 2", "Atmos Energy Corporation", "UTILITY", "4922"), "multifamily"),
    (row("THE VIREO APARTMENTS", "Whoever LLC", "", "1521"), "multifamily"),
    (row("CEDAR TOWNHOMES", "Whoever LLC"), "townhome"),
    (row("GRAND MAGNOLIA SEC 4", "Castlerock Communities", "MULTI-FAMILY RESIDENTIAL", "1521"), "single_family"),
    (row("HUTTO TOYOTA", "Dealer Builders LLC", "COMMERCIAL", "1541"), "commercial"),
    (row("ALTA SERGEANT", "X", "COMMERCIAL", "1542"), "multifamily"),          # brand beats a commercial CT
    (row("ALTA LOMA 138KV REBUILD", "X", "UTILITY", "4911"), "commercial"),   # place name, not the brand
    (row("SOME PROJECT", "X", "", "1522", 12.0), "multifamily"),              # SIC 1522, apartment-sized site
    (row("SOME PROJECT", "X", "", "1522", 2.0), None),                        # too small to call: the model decides
])
def test_rules(r, expected):
    assert decide_rules(r) == expected


def test_nonresidential_guard_blocks_roster_surnames():
    assert mf_override(row("MCCLAINS RV SERVICE CENTER", "Morgan Group Inc")) != "multifamily"
