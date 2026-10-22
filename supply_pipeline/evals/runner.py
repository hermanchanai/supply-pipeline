"""Run a classifier module against goldens and collect its outputs. No scoring here."""
from __future__ import annotations

import importlib
import time
from dataclasses import dataclass, field, replace

from .policy import CLASSIFIER_SURFACES, LLM_FEATURE_TAG


@dataclass
class ClassifierRunResult:
    golden_id: int
    input_row_id: str
    expected_class: str
    actual_class: str | None
    latency_ms: int
    error: str | None = None
    cohort_tags: dict = field(default_factory=dict)


@dataclass
class ClassifierRunSummary:
    surface: str
    model: str
    provider: str
    results: list[ClassifierRunResult]
    cost_usd: float


class Temperature0:
    """Eval calls run at temperature 0 so a re-run measures prompt or model drift, not
    sampling noise. Production calls keep the vendor default; the classifier code is not
    edited for the eval, the provider is wrapped instead."""

    def __init__(self, inner):
        self.inner = inner
        self.model = inner.model
        self.name = getattr(inner, "name", "?")

    def complete(self, req, **kw):
        kw["feature"] = LLM_FEATURE_TAG
        return self.inner.complete(replace(req, temperature=0.0), **kw)


def import_surface(surface: str):
    cfg = CLASSIFIER_SURFACES[surface]
    mod = importlib.import_module(cfg["module"])
    return mod, getattr(mod, cfg["fn"])


def run_classifier_against_goldens(surface: str, goldens: list, provider) -> ClassifierRunSummary:
    _mod, classify = import_surface(surface)
    wrapped = Temperature0(provider)
    spent0 = getattr(getattr(provider, "guard", None), "spent_usd", 0.0)
    results = []
    for g in goldens:
        t0 = time.perf_counter()
        actual, err = None, None
        try:
            actual = classify(wrapped, g.input_payload)
        except Exception as e:   # one bad row is a scored failure, not a crashed run
            err = f"{type(e).__name__}: {e}"[:300]
        results.append(ClassifierRunResult(g.id, g.input_row_id, g.expected_class, actual,
                                           int((time.perf_counter() - t0) * 1000), err, g.cohort_tags))
    spent1 = getattr(getattr(provider, "guard", None), "spent_usd", 0.0)
    return ClassifierRunSummary(surface, provider.model, getattr(provider, "name", "?"), results,
                                round(spent1 - spent0, 6))
