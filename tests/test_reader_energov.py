"""Permit-portal JSON reader (Tyler EnerGov) on a recorded Henderson plan search page."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from supply_pipeline.readers import energov
from tests.fakes import FakeResponse, RecordedSession, json_response

TENANT = replace(energov.HENDERSON, keywords=("tentative",), max_pages=3)


def session_one_page():
    return RecordedSession().add("POST", "energov/search/search",
                                 json_response("energov/henderson_tentative_p1.json"))


def test_sweep_posts_the_plan_filter_and_stops_on_a_short_page(store):
    s = session_one_page()
    res = energov.run(store, TENANT, session=s, page_size=50)
    body = s.calls[0]["json"]
    assert (body["SearchModule"], body["FilterModule"], body["Keyword"], body["SortBy"]) == (1, 3, "tentative", "ApplyDate")
    assert len(s.calls) == 1                     # 5 results < page size 50: done
    rows = store.rows("select * from county_permits.entitlement_cases order by case_number")
    assert res.fetched == 5 and len(rows) == res.upserted
    assert {r["stage"] for r in rows} <= {"plat", "rezoning", "site_plan", "sup", "design_review", "variance"}
    r = rows[0]
    assert r["jurisdiction"] == "henderson_nv" and r["county"] == "CLARK" and r["link"].startswith(TENANT.base_url)
    assert set(r["raw_json"]) <= set(energov.RAW_KEYS)


def test_keyword_slices_dedupe_by_case_id():
    s = session_one_page()
    t = replace(TENANT, keywords=("tentative", "map"))
    cases = list(energov.sweep_plans(s, t, page_size=50))
    assert len(s.calls) == 2 and len(cases) == 5


def test_a_failed_page_is_incomplete_not_empty():
    s = RecordedSession().add("POST", "search", FakeResponse(b"<html>busy</html>", status=503, content_type="text/html"))
    with pytest.raises(energov.IncompleteSweep, match="HTTP 503"):
        list(energov.sweep_plans(s, TENANT))


def test_stage_allowlist_and_denylist():
    assert energov.stage_for("Tentative Map") == "plat"
    assert energov.stage_for("Rezoning") == "rezoning"
    assert energov.stage_for("Conditional Use Permit") == "sup"
    assert energov.stage_for("Design Review") == "design_review"
    assert energov.stage_for("Zoning Verification Letter") is None
    assert energov.stage_for("Sign Permit") is None
    assert energov.stage_for("Business License") is None
    assert energov.lifecycle("Pending") == "in_review" and energov.lifecycle("Withdrawn") == "terminal"


def test_to_row_drops_non_entitlement_cases():
    case = json.loads(json_response("energov/henderson_tentative_p1.json").content)["Result"]["EntityResults"][0]
    assert energov.to_row({**case, "CaseType": "Sign Permit"}, TENANT) is None
    assert energov.to_row(case, TENANT)["stage"] == "plat"
