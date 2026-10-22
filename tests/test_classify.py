"""Classifiers. Spec: the production prompt and the exact user message go through
provider.complete with max_tokens=10 and the provider's model; replies map onto the enum;
the Atlanta message never carries an email address, only its domain; the lexicon overrides
the base only across a business bucket."""
from __future__ import annotations

import json

from supply_pipeline.classify import azdeq, epd, epd_enriched, lexicon, normalize
from supply_pipeline.llm.provider import Completion, Usage


class FakeProvider:
    name, model = "fake", "some-model"

    def __init__(self, text):
        self.text, self.calls = text, []

    def complete(self, req, **kw):
        self.calls.append((req, kw))
        return Completion(text=self.text, usage=Usage())


ROW = {"facility_name": "Example Townhomes", "application_name": None, "address": "1 Main St",
       "city": "MESA", "parsed_county": "Maricopa", "acres_disturbed_project": None,
       "acres_disturbed_operations": 2.5}


def test_azdeq_sends_the_prompt_and_maps_the_reply():
    p = FakeProvider(" Single-Family \n")
    assert azdeq.classify(p, ROW) == "single_family"
    req, kw = p.calls[0]
    assert (req.system, req.user, req.max_tokens, req.model) == (azdeq.SYSTEM_PROMPT, azdeq.build_user_msg(ROW),
                                                                  10, "some-model")
    assert kw["feature"] == "azdeq_classify"
    assert azdeq.classify(FakeProvider("garbage"), ROW) == "unknown"


def test_normalize():
    assert normalize("Commercial.") == "commercial"
    assert normalize("apartments") == "multifamily"
    assert normalize("retail") == "commercial"
    assert normalize("commercial", {"single_family", "unknown"}) == "unknown"


def test_epd_message_carries_domains_never_addresses():
    row = {"facility_name": "Example Ridge", "email_domains": ["someone@builder.example", "mf.example"]}
    msg = json.loads(epd.build_user_msg(row))
    assert msg["email_domains"] == ["builder.example", "mf.example"]
    assert "someone" not in epd.build_user_msg(row) and "@" not in epd.build_user_msg(row)
    assert "email_domains" not in json.loads(epd.build_user_msg({"facility_name": "X"}))


TABLE = {"examplebuilder": {"bucket": "for_sale", "typical": "single_family"},
         "examplemf": {"bucket": "rental", "typical": "multifamily"}}


def test_lexicon_longest_key_wins():
    t = {"mf": {"typical": "multifamily"}, "examplemf": {"typical": "townhome"}}
    assert lexicon.lookup(t, "Example MF Owner LLC")["key"] == "examplemf"
    assert lexicon.lookup(t, None, "") is None


def test_enriched_overrides_only_across_a_bucket():
    row = {"facility_name": "Oak Park", "owner_name": "ExampleMF Holdings LLC"}
    out = epd_enriched.classify_verbose(FakeProvider("single_family"), row, TABLE)
    assert (out["dwelling_type"], out["source"]) == ("multifamily", "lexicon")
    row2 = {"facility_name": "Oak Park", "owner_name": "ExampleBuilder LLC"}
    out2 = epd_enriched.classify_verbose(FakeProvider("townhome"), row2, TABLE)
    assert (out2["dwelling_type"], out2["source"]) == ("townhome", "base")   # SF<->TH stays with base
    out3 = epd_enriched.classify_verbose(FakeProvider("single_family"),
                                         {"facility_name": "Oak Park Apartments", "owner_name": "ExampleBuilder"}, TABLE)
    assert out3["source"] == "name"


def test_published_lexicon_loads():
    t = lexicon.load()
    assert len(t) > 50 and all("typical" in v for v in t.values())
