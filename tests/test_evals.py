"""Eval harness.

Spec: (1) the comparator ranks errors by business impact; (2) the Phoenix golden set
replayed through the real classifier code and scored by the real report reproduces the
published row: 65 filings, 84.6% exact (55), 86.2% right bucket (56), 7 rent/sale errors;
(3) a business_miss fails the run once calibration has closed; (4) goldens carry no PII
columns and an honest label_method."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from supply_pipeline.evals import comparator as C
from supply_pipeline.evals import corpus, report, runner, validators
from supply_pipeline.llm.provider import ReplayProvider

ROOT = Path(__file__).resolve().parent.parent
REC = ROOT / "data/recorded/azdeq_classify_haiku-4-5_2026-10-03.jsonl"
SITE_ROW = {"metro": "Phoenix", "n": 65, "exact": "84.6%", "exactN": 55, "bucket": "86.2%", "bucketN": 56, "miss": 7}


def test_comparator_severities():
    assert C.compare_classifier("single_family", "single_family").severity == "pass"
    assert C.compare_classifier("single_family", "townhome").severity == "cosmetic_miss"
    assert C.compare_classifier("single_family", "multifamily").severity == "business_miss"
    assert C.compare_classifier("multifamily", "commercial").severity == "business_miss"
    assert C.compare_classifier("unknown", "townhome").severity == "overcommit"
    assert C.compare_classifier("townhome", "unknown").severity == "abstain_miss"
    assert C.compare_classifier("townhome", "castle").severity == "validation_fail"


def test_extractor_tolerances():
    r = C.compare_extractor({"total_lots": 192, "subdivision_acres": 6.0, "water_provider": "EPCOR",
                             "amenities": ["Pool", "tot lot"], "extraction_notes": "x"},
                            {"total_lots": 192, "subdivision_acres": 6.2, "water_provider": "EPCOR Water",
                             "amenities": ["tot lot", "pool"], "extraction_notes": "y"})
    assert r.passed
    r2 = C.compare_extractor({"total_lots": None}, {"total_lots": 40})
    assert r2.severity == "hallucination"
    assert C.compare_extractor({"effective_date": "2026-05-04"}, {"effective_date": "2026-06-04"}).severity == "field_drift"


def test_validators():
    assert validators.validate_classifier_output("Townhome") == []
    assert validators.validate_classifier_output("") == ["classifier returned empty/null"]
    assert validators.validate_extractor_output({"total_lots": 0}) == ["total_lots=0 outside [1, 20000]"]
    assert "bounding box" in validators.validate_extractor_output(
        {"total_lots": 5, "latitude": 40.0, "longitude": -112.0}, "phoenix")[0]


def test_phoenix_replay_reproduces_the_published_row():
    goldens = corpus.load_classifier_goldens("azdeq_classify")
    assert len(goldens) == 65
    s = runner.run_classifier_against_goldens("azdeq_classify", goldens,
                                              ReplayProvider(REC, model="claude-haiku-4-5"))
    assert all(r.error is None for r in s.results)
    p = report.process_classifier_run(s, baseline=corpus.baseline_for("azdeq_classify"), today=date(2026, 10, 3))
    assert p.site_row("Phoenix") == SITE_ROW
    assert p.exit_code == 1 and p.alert_severity == "critical"          # 7 business misses fail the run
    assert p.severity_counts == {"pass": 55, "cosmetic_miss": 1, "business_miss": 7, "overcommit": 1,
                                 "abstain_miss": 1, "validation_fail": 0}


def test_inside_calibration_a_business_miss_only_warns():
    goldens = corpus.load_classifier_goldens("azdeq_classify")
    s = runner.run_classifier_against_goldens("azdeq_classify", goldens,
                                              ReplayProvider(REC, model="claude-haiku-4-5"))
    assert report.process_classifier_run(s, baseline=None, today=date(2026, 6, 10)).exit_code == 0


def test_a_regression_against_the_baseline_is_detected():
    goldens = corpus.load_classifier_goldens("azdeq_classify")
    s = runner.run_classifier_against_goldens("azdeq_classify", goldens,
                                              ReplayProvider(REC, model="claude-haiku-4-5"))
    p = report.process_classifier_run(s, baseline={"pass_rate": 0.95}, today=date(2026, 10, 3))
    assert p.regression_detected and "pass rate dropped" in p.alert_message


ALLOWED_INPUTS = {
    "azdeq_classify": {"facility_name", "application_name", "address", "city", "parsed_county",
                       "acres_disturbed_project", "acres_disturbed_operations"},
    "epd_classify_dwelling": {"facility_name", "common_development_name", "formerly_known_as", "site_address",
                              "site_city", "site_county", "disturbed_acres", "construction_activity_types"},
}


def test_goldens_carry_only_allowed_inputs_and_a_label_method():
    """Positive list: no owner, contact, email or narrative field can ride along."""
    for surface, allowed in ALLOWED_INPUTS.items():
        rows = [json.loads(x) for x in (ROOT / f"data/goldens/{surface}.jsonl").read_text().splitlines()]
        for r in rows:
            assert set(r["input_payload"]) <= allowed
            assert not re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", json.dumps(r), re.I)   # no email address
            assert r["label_method"] == "llm_web_research"
            assert r["labeled_by_db"]
