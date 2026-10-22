"""Store.upsert semantics. Spec: a re-sweep updates plain columns; an incoming NULL on an
enrichment column keeps the stored value; coordinates move only as a complete pair."""
from __future__ import annotations

from supply_pipeline.store import dedupe, upsert_sql

CASE = {"msa": "las_vegas", "jurisdiction": "henderson_nv", "source_type": "tyler_energov_plan",
        "case_number": "C-1", "stage": "plat", "project_name": "Example Ridge",
        "units_filed": 120, "latitude": 36.0, "longitude": -115.0}
KW = dict(key=("jurisdiction", "case_number"), coalesce=("project_name", "units_filed"),
          coord_pair=("latitude", "longitude"))


def test_sql_shape():
    sql = upsert_sql("t.x", ["a", "b", "lat", "lon"], key=("a",), coalesce=("b",), coord_pair=("lat", "lon"))
    assert "ON CONFLICT (a) DO UPDATE SET" in sql
    assert "b = COALESCE(EXCLUDED.b, t.b)" in sql
    assert "lat = CASE WHEN EXCLUDED.lat IS NOT NULL AND EXCLUDED.lon IS NOT NULL THEN EXCLUDED.lat ELSE t.lat END" in sql
    assert " a = EXCLUDED.a" not in sql


def test_dedupe_keeps_last_and_drops_null_keys():
    rows = [{"k": 1, "v": "old"}, {"k": None, "v": "x"}, {"k": 1, "v": "new"}]
    assert dedupe(rows, ("k",)) == [{"k": 1, "v": "new"}]


def test_resweep_keeps_enrichment_and_coordinates(store):
    store.upsert("county_permits.entitlement_cases", [CASE], **KW)
    thinner = {**CASE, "stage": "rezoning", "project_name": None, "units_filed": None,
               "latitude": None, "longitude": None}
    store.upsert("county_permits.entitlement_cases", [thinner], **KW)
    r = store.rows("select * from county_permits.entitlement_cases")[0]
    assert r["stage"] == "rezoning"                       # plain column follows the source
    assert (r["project_name"], r["units_filed"]) == ("Example Ridge", 120)
    assert (r["latitude"], r["longitude"]) == (36.0, -115.0)


def test_half_a_coordinate_never_lands(store):
    store.upsert("county_permits.entitlement_cases", [CASE], **KW)
    store.upsert("county_permits.entitlement_cases", [{**CASE, "latitude": 36.5, "longitude": None}], **KW)
    r = store.rows("select latitude, longitude from county_permits.entitlement_cases")[0]
    assert (r["latitude"], r["longitude"]) == (36.0, -115.0)
    store.upsert("county_permits.entitlement_cases", [{**CASE, "latitude": 36.5, "longitude": -115.5}], **KW)
    r = store.rows("select latitude, longitude from county_permits.entitlement_cases")[0]
    assert (r["latitude"], r["longitude"]) == (36.5, -115.5)
