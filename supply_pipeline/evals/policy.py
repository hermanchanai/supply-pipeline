"""Eval policy: surfaces, business buckets, thresholds. One place to change a number."""
from __future__ import annotations

from datetime import date

CLASSIFIER_SURFACES = {
    # Phoenix: ADEQ construction NOIs, 6 classes (adds 'commercial'). Name-only input.
    "azdeq_classify": {"module": "supply_pipeline.classify.azdeq", "fn": "classify", "msa": "phoenix"},
    # Atlanta: GA EPD residential NOIs, 5 classes.
    "epd_classify_dwelling": {"module": "supply_pipeline.classify.epd", "fn": "classify", "msa": "atlanta"},
    # Atlanta base classifier + developer lexicon, scored on the same goldens. Leaky by
    # construction (the lexicon was built while labelling them), so never a headline number.
    "epd_classify_enriched": {"module": "supply_pipeline.classify.epd_enriched", "fn": "classify",
                              "golden_surface": "epd_classify_dwelling", "msa": "atlanta"},
}

CLASSIFIER_VALID_CLASSES = {"single_family", "townhome", "multifamily", "mixed", "commercial", "unknown"}

# Business buckets. For-sale versus for-rent is the distinction a rental underwrite cares
# about: single-family and townhome are both for-sale product, so an SF<->TH error is
# cosmetic. Apartments are rental supply. An error that crosses for_sale <-> rental is a
# business error; one inside a bucket is not.
BUSINESS_BUCKETS = {
    "single_family": "for_sale",
    "townhome": "for_sale",
    "multifamily": "rental",
    "mixed": "mixed",
    "commercial": "commercial",   # a residential<->commercial crossing also corrupts supply counts
    "unknown": "unknown",
}


def business_bucket(cls: str | None) -> str:
    if not cls:
        return "unknown"
    return BUSINESS_BUCKETS.get(str(cls).strip().lower(), "unknown")


# Per-field tolerances for extractor comparisons (compare_extractor).
EXTRACTOR_TOLERANCES: dict[str, dict] = {
    "disturbed_acres": {"kind": "abs_or_pct", "abs": 0.5, "pct": 0.05},
    "subdivision_acres": {"kind": "abs_or_pct", "abs": 0.5, "pct": 0.05},
    "latitude": {"kind": "abs", "tol": 0.001},
    "longitude": {"kind": "abs", "tol": 0.001},
    "total_lots": {"kind": "exact"},
    "effective_date": {"kind": "abs_days", "days": 7},
    "estimated_completion_date": {"kind": "abs_days", "days": 7},
    "water_provider": {"kind": "substring"},
    "amenities": {"kind": "set"},
    "extraction_notes": {"kind": "skip"},
}

# The calibration window closed 2026-06-22: since then a business_miss or a hard
# regression fails the run (exit 1). Inside the window they only warned.
CALIBRATION_WINDOW_END = date(2026, 6, 22)
DEFAULT_WARN_PCT_DROP = 0.02
DEFAULT_HARDFAIL_PCT_DROP = 0.05
REGRESSION_THRESHOLDS: dict[str, dict[str, float]] = {}

MAX_USD_PER_RUN = 5.0     # spend cap for a live re-score
LLM_FEATURE_TAG = "eval"


def regression_thresholds_for(surface: str) -> tuple[float, float]:
    e = REGRESSION_THRESHOLDS.get(surface, {})
    return e.get("warn_pct_drop", DEFAULT_WARN_PCT_DROP), e.get("hardfail_pct_drop", DEFAULT_HARDFAIL_PCT_DROP)
