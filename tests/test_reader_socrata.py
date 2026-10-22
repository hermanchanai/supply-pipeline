"""Open-data API reader on a recorded City of Austin Socrata response."""
from __future__ import annotations

from dataclasses import replace

from supply_pipeline.readers import socrata
from tests.fakes import FakeResponse, RecordedSession, json_response


def test_loads_cast_rows(store):
    s = RecordedSession().add("GET", "it4s-wgjk.json", json_response("socrata/austin_it4s_wgjk.json"))
    res = socrata.run(store, session=s)
    assert (res.fetched, res.upserted) == (3, 3)
    r = store.rows("select * from coa.subdivision_review_cases order by folderrsn")[0]
    assert isinstance(r["proposed_no_of_lots"], int)
    assert r["application_start_date"] is not None
    assert s.calls[0]["params"]["$order"] == ":id"


def test_pages_by_limit_and_offset():
    page = FakeResponse(b'[{"folderrsn": "1"}, {"folderrsn": "2"}]')
    last = FakeResponse(b'[{"folderrsn": "3"}]')
    s = RecordedSession()
    s.add("GET", "it4s", page, when=lambda r: r["params"]["$offset"] == 0)
    s.add("GET", "it4s", last, when=lambda r: r["params"]["$offset"] == 2)
    out = socrata.fetch(s, replace(socrata.AUSTIN_SUBDIVISIONS, page_size=2))
    assert [r["folderrsn"] for r in out] == ["1", "2", "3"]


def test_incremental_uses_the_date_field():
    s = RecordedSession().add("GET", "it4s", FakeResponse(b"[]"))
    socrata.fetch(s, socrata.AUSTIN_SUBDIVISIONS, since="2026-01-01")
    p = s.calls[0]["params"]
    assert p["$where"] == "application_start_date > '2026-01-01'"
    assert p["$order"] == "application_start_date ASC"


def test_error_envelope_raises():
    s = RecordedSession().add("GET", "it4s", FakeResponse(b'{"error": true, "message": "bad query"}'))
    try:
        socrata.fetch(s, socrata.AUSTIN_SUBDIVISIONS)
    except RuntimeError as e:
        assert "error envelope" in str(e)
    else:
        raise AssertionError("a Socrata error must not read as an empty dataset")


def test_casts():
    assert socrata.to_int("50.0") == 50 and socrata.to_int(".") is None
    assert socrata.to_float("") is None and socrata.to_date("2026-10-09T00:00:00.000Z") == "2026-10-09"
