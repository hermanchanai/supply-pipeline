"""GIS map service reader on recorded Metro Nashville responses."""
from __future__ import annotations

import json
from dataclasses import replace

from supply_pipeline.readers import arcgis, derived
from tests.fakes import FakeResponse, RecordedSession, fixture_bytes, json_response


def permits_session() -> RecordedSession:
    s = RecordedSession()
    for off in (0, 2):
        s.add("GET", "Building_Permits_Issued_2", json_response(f"arcgis/nashville_permits_offset{off}.json"),
              when=lambda req, off=off: req["params"]["resultOffset"] == off)
    s.add("GET", "Building_Permits_Issued_2", FakeResponse(b'{"features": []}'),
          when=lambda req: req["params"]["resultOffset"] == 4)
    return s


def test_pages_until_an_empty_page_and_loads_rows(store):
    layer = replace(arcgis.NASHVILLE_PERMITS, page_size=2)
    s = permits_session()
    res = arcgis.run(store, layer, session=s)
    assert [c["params"]["resultOffset"] for c in s.calls] == [0, 2, 4]
    assert res.fetched == 4 and res.upserted == 4
    rows = store.rows("select * from nashville.building_permits_issued order by permit_number")
    assert len(rows) == 4
    r = next(x for x in rows if x["permit_number"] == "2023047626")
    assert r["permit_subtype_description"] == "Multifamily, Townhome"
    assert r["date_issued"].isoformat() == "2024-01-23"      # epoch ms 1705989600000 -> date (UTC)
    assert "contact" not in r                                # no contact column at all


def test_short_page_with_transfer_limit_keeps_paging():
    """A server may serve a short page mid-stream; exceededTransferLimit says more remain."""
    p0 = json.loads(fixture_bytes("arcgis/nashville_permits_offset0.json"))
    p0["features"] = p0["features"][:1]
    p0["exceededTransferLimit"] = True
    p1 = json.loads(fixture_bytes("arcgis/nashville_permits_offset2.json"))
    p1["exceededTransferLimit"] = False
    s = RecordedSession()
    s.add("GET", "query", FakeResponse(json.dumps(p0).encode()), when=lambda r: r["params"]["resultOffset"] == 0)
    s.add("GET", "query", FakeResponse(json.dumps(p1).encode()), when=lambda r: r["params"]["resultOffset"] == 1)
    feats = arcgis.fetch_all(s, replace(arcgis.NASHVILLE_PERMITS, page_size=3))
    assert len(feats) == 3
    assert [c["params"]["resultOffset"] for c in s.calls] == [0, 1]


def test_arcgis_error_body_raises():
    s = RecordedSession().add("GET", "query", FakeResponse(b'{"error": {"code": 400, "message": "Invalid"}}'))
    try:
        arcgis.fetch_all(s, arcgis.NASHVILLE_PERMITS)
    except RuntimeError as e:
        assert "ArcGIS error" in str(e)
    else:
        raise AssertionError("an ArcGIS error body must not read as an empty layer")


def test_since_filter_is_epoch_ms():
    assert arcgis.where_since(arcgis.NASHVILLE_PERMITS, "2026-01-01") == "Date_Issued >= 1767225600000"
    assert arcgis.where_since(arcgis.NASHVILLE_PERMITS, None) == "1=1"


def test_planning_cases_drop_contacts_and_redact_captions(store):
    s = RecordedSession().add("GET", "Development_Tracker_Cases_view",
                              json_response("arcgis/nashville_planning.geojson"))
    res = arcgis.run(store, arcgis.NASHVILLE_PLANNING, session=s)
    assert res.upserted == 7
    cols = {r["column_name"] for r in store.rows(
        "select column_name from information_schema.columns where table_schema='nashville' "
        "and table_name='planning_dev_cases'")}
    assert not {c for c in cols if "applicant" in c or "email" in c or "phone" in c or "reviewer" in c}
    captions = [r["case_caption"] for r in store.rows("select case_caption from nashville.planning_dev_cases")]
    assert captions and not any("requested by" in (c or "").lower() for c in captions)


def test_redact_caption():
    c = "A request to rezone from R8 to SP (4.0 acres), requested by A Person, applicant; B Person, owner."
    assert arcgis.redact_caption(c) == "A request to rezone from R8 to SP (4.0 acres)."
    assert arcgis.redact_caption(None) is None


def test_derived_view_narrows_planning_cases_to_entitlements(store):
    s = RecordedSession().add("GET", "Development_Tracker_Cases_view",
                              json_response("arcgis/nashville_planning.geojson"))
    arcgis.run(store, arcgis.NASHVILLE_PLANNING, session=s)
    out = derived.rows(store)
    # 4 of the 7 recorded cases are rezonings or plats; easements and downtown code are not.
    assert len(out) == 4
    assert {r["stage"] for r in out} == {"rezoning", "plat"}
    assert all(r["msa"] == "nashville" and r["county"] == "DAVIDSON" for r in out)
    assert derived.run(store).fetched == 4
    served = store.rows("select count(*) as n from county_permits.v_entitlement_served "
                        "where jurisdiction = 'davidson_metro'")[0]["n"]
    assert served == 4
