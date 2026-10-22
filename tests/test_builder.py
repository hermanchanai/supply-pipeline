"""Snapshot builder.

Spec:
  1. It refuses rather than mis-describe a feed: an untagged tracked source, an unknown
     metro, an unknown method, or an example id that is untracked / tagged otherwise.
  2. On the bundled sample it reproduces the SHAPE of the public page's JSON (same keys at
     every level, same methods in the same order, same metros), the page's per-method and
     per-metro feed counts (the registry is frozen at the page's snapshot), and each method's
     example-feed record count equals that feed's frozen coverage count.
  3. The same sample always produces the same JSON.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from supply_pipeline.snapshot import builder as b
from supply_pipeline.snapshot import sample

ROOT = Path(__file__).resolve().parent.parent
SITE = json.loads((ROOT / "tests/fixtures/site/supply-database.json").read_text())


def registry() -> list[dict]:
    return [{"id": sid, "msa": "Atlanta", "source_label": f"src {sid}", "access_method": m}
            for m, sid in b.EXAMPLES.items()]


def test_valid_registry_passes():
    b.validate_registry(registry())


def test_untagged_tracked_source_refuses_and_names_it():
    rows = registry() + [{"id": 9001, "msa": "Tampa", "source_label": "New county feed", "access_method": None}]
    with pytest.raises(b.Refusal, match=r"9001 Tampa — New county feed"):
        b.validate_registry(rows)


def test_unknown_metro_refuses():
    with pytest.raises(b.Refusal, match="Dallas"):
        b.validate_registry(registry() + [{"id": 9002, "msa": "Dallas", "source_label": "x",
                                           "access_method": "arcgis"}])


def test_unknown_method_refuses():
    with pytest.raises(b.Refusal, match="ftp"):
        b.validate_registry(registry() + [{"id": 9003, "msa": "Atlanta", "source_label": "x",
                                           "access_method": "ftp"}])


def test_example_not_tracked_refuses():
    with pytest.raises(b.Refusal, match=r"EXAMPLES\['pdf'\]"):
        b.validate_registry([r for r in registry() if r["id"] != b.EXAMPLES["pdf"]])


def test_example_with_wrong_method_refuses():
    rows = registry()
    for r in rows:
        if r["id"] == b.EXAMPLES["browser"]:
            r["access_method"] = "html_scrape"
    with pytest.raises(b.Refusal, match=r"EXAMPLES\['browser'\].*'html_scrape'"):
        b.validate_registry(rows)


def test_methods_match_the_schema_check_vocabulary():
    import re
    sql = (ROOT / "schema/001_registry.sql").read_text()
    check = re.search(r"access_method IN \((.*?)\)\)", sql, re.S)
    assert set(re.findall(r"'([a-z_]+)'", check.group(1))) == set(b.METHODS)


def test_every_method_has_an_example_wording_and_a_reader():
    from supply_pipeline.readers import READERS, reader
    assert set(b.EXAMPLES) == set(b.EXAMPLE_WHAT) == set(b.METHODS) == set(READERS)
    for m, sid in b.EXAMPLES.items():
        assert reader(m).EXAMPLE_FEED == sid and reader(m).METHOD == m


def test_place_prefers_city_then_county():
    assert b.place({"city": "CANTON", "county": "Cherokee"}) == "Canton"
    assert b.place({"city": None, "county": "fort bend"}) == "Fort Bend County"
    assert b.place({"city": "", "county": "Travis County"}) == "Travis County"
    assert b.place({}) is None


def test_feed_age_takes_the_later_of_load_and_record_date():
    today = date(2026, 10, 21)
    assert b.feed_age({"last_ingested": "2026-10-01T00:00:00+00:00", "latest_data": "2026-10-19"}, today) == 2
    assert b.feed_age({"last_ingested": None, "latest_data": "2027-01-01"}, today) is None   # future date ignored
    assert b.feed_age({"last_ingested": None, "latest_data": None}, today) is None


# ---------------------------------------------------------------- on the sample
@pytest.fixture
def built(store):
    sample.load(store, ROOT / "sample")
    m = sample.manifest(ROOT / "sample")
    return b.build(store, as_of=date.fromisoformat(m["as_of"]),
                   generated_at=datetime.fromisoformat(m["frozen_at"]))


def shape(v):
    if isinstance(v, dict):
        return {k: shape(x) for k, x in v.items()}
    if isinstance(v, list):
        return [shape(v[0])] if v else []
    return type(v).__name__ if not isinstance(v, bool | int | float) else "number"


def test_same_shape_as_the_public_page(built):
    assert set(built) == set(SITE)
    assert shape(built["headline"]) == shape(SITE["headline"])
    assert shape(built["methods"][0]) == shape(SITE["methods"][0])
    assert shape(built["markets"][0]) == shape(SITE["markets"][0])
    assert shape(built["permit_products"][0]) == shape(SITE["permit_products"][0])
    assert shape(built["entitlement_types"][0]) == shape(SITE["entitlement_types"][0])
    assert {k: shape(v[0]) for k, v in built["samples"].items()} == \
        {k: shape(v[0]) for k, v in SITE["samples"].items()}
    assert [m["method"] for m in built["methods"]] == [m["method"] for m in SITE["methods"]]
    assert built["metros"] == SITE["metros"]
    assert [f["bucket"] for f in built["freshness"]] == [f["bucket"] for f in SITE["freshness"]]
    assert built["permit_stages"] == SITE["permit_stages"]


def test_feed_counts_match_the_page(built):
    assert built["headline"]["tracked_feeds"] == SITE["headline"]["tracked_feeds"] == 254
    assert {m["method"]: (m["feeds"], m["metros"]) for m in built["methods"]} == \
        {m["method"]: (m["feeds"], m["metros"]) for m in SITE["methods"]}
    keys = ("feeds", "early", "entitlement", "late", "methods")
    assert {m["market"]: {k: m[k] for k in keys} for m in built["markets"]} == \
        {m["market"]: {k: m[k] for k in keys} for m in SITE["markets"]}


def test_example_counts_equal_the_frozen_coverage(built):
    reg = {r["id"]: r for r in sample.read_table(ROOT / "sample", "registry.pipeline_sources")}
    cov = {(r["msa"], r["source_label"]): r for r in sample.read_table(ROOT / "sample", "registry.pipeline_coverage")}
    for m in built["methods"]:
        src = reg[b.EXAMPLES[m["method"]]]
        assert m["example"]["records"] == cov[(src["msa"], src["source_label"])]["row_count"]
        assert m["example"]["market"] == b.BY_REGISTRY[src["msa"]]


def test_samples_are_full_and_named(built):
    assert all(len(v) == 15 for v in built["samples"].values())
    for rows in built["samples"].values():
        assert all(r["name"] and 10 <= r["units"] <= 2000 for r in rows)


def test_deterministic(built, store):
    m = sample.manifest(ROOT / "sample")
    again = b.build(store, as_of=date.fromisoformat(m["as_of"]),
                    generated_at=datetime.fromisoformat(m["frozen_at"]))
    assert json.dumps(again, sort_keys=True) == json.dumps(built, sort_keys=True)
