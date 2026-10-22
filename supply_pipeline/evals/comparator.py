"""Pure comparison: no I/O. (expected, actual) -> a scored case.

Classifier severities, ranked by business impact:
  pass             exact match
  cosmetic_miss    wrong class, same business bucket (SF <-> TH)
  business_miss    crosses a bucket on two confident classes (e.g. SF <-> MF): corrupts
                   rental-supply counts. The one that matters.
  overcommit       golden = unknown (undeterminable) but the model committed to a class
  abstain_miss     golden is confident, the model returned unknown
  validation_fail  output not in the enum
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .policy import CLASSIFIER_VALID_CLASSES, EXTRACTOR_TOLERANCES, business_bucket


@dataclass
class FieldDiff:
    field: str
    expected: Any
    actual: Any
    passed: bool
    tolerance_kind: str
    severity: str
    note: str = ""


@dataclass
class CaseResult:
    passed: bool
    severity: str
    field_diffs: list[FieldDiff] = field(default_factory=list)
    note: str = ""
    expected_bucket: str = ""
    actual_bucket: str = ""
    bucket_passed: bool = True


def norm_class(v) -> str:
    return "" if v is None else str(v).strip().lower().replace(" ", "_").replace("-", "_")


def compare_classifier(expected: str, actual: str) -> CaseResult:
    exp, act = norm_class(expected), norm_class(actual)
    if exp not in CLASSIFIER_VALID_CLASSES:
        return CaseResult(False, "validation_fail", note=f"expected_class {expected!r} not in enum")
    if act not in CLASSIFIER_VALID_CLASSES:
        return CaseResult(False, "validation_fail", note=f"actual {actual!r} not in enum",
                          expected_bucket=business_bucket(exp), actual_bucket="invalid", bucket_passed=False)
    eb, ab = business_bucket(exp), business_bucket(act)
    if exp == act:
        return CaseResult(True, "pass", expected_bucket=eb, actual_bucket=ab, bucket_passed=True)
    if exp == "unknown":
        sev = "overcommit"
    elif act == "unknown":
        sev = "abstain_miss"
    elif eb == ab:
        sev = "cosmetic_miss"
    else:
        sev = "business_miss"
    return CaseResult(False, sev, expected_bucket=eb, actual_bucket=ab, bucket_passed=eb == ab,
                      field_diffs=[FieldDiff("class", exp, act, False, "exact", sev)])


def compare_extractor(expected: dict, actual: dict) -> CaseResult:
    diffs = []
    for k in sorted(set(expected) | set(actual)):
        rule = EXTRACTOR_TOLERANCES.get(k, {"kind": "exact_ci"})
        if rule["kind"] == "skip":
            continue
        diffs.append(_compare_one(k, expected.get(k), actual.get(k), rule))
    rank = {"pass": 0, "field_drift": 1, "miss": 2, "hallucination": 3, "validation_fail": 4}
    worst = max((d.severity for d in diffs), key=lambda s: rank.get(s, 0), default="pass")
    ok = all(d.passed for d in diffs)
    return CaseResult(ok, "pass" if ok else worst, field_diffs=diffs)


def _compare_one(name: str, exp, act, rule: dict) -> FieldDiff:
    kind = rule["kind"]
    if _is_null(exp) and _is_null(act):
        return FieldDiff(name, exp, act, True, kind, "pass")
    if _is_null(exp):
        return FieldDiff(name, exp, act, False, kind, "hallucination", "golden=null, actual gave a value")
    if _is_null(act):
        return FieldDiff(name, exp, act, False, kind, "miss", "golden has value, actual returned null")
    try:
        if kind == "exact":
            ok = exp == act
        elif kind == "exact_ci":
            ok = _norm_str(exp) == _norm_str(act)
        elif kind == "abs":
            ok = abs(float(exp) - float(act)) <= rule["tol"]
        elif kind == "abs_or_pct":
            ok = abs(float(exp) - float(act)) <= max(rule["abs"], rule["pct"] * abs(float(exp)))
        elif kind == "abs_days":
            de, da = _to_date(exp), _to_date(act)
            if de is None or da is None:
                return FieldDiff(name, exp, act, False, kind, "field_drift", "unparseable date")
            ok = abs((de - da).days) <= rule["days"]
        elif kind == "substring":
            e, a = _norm_str(exp), _norm_str(act)
            ok = bool(e and a) and (e in a or a in e)
        elif kind == "set":
            ok = {_norm_str(x) for x in exp} == {_norm_str(x) for x in act}
        else:
            return FieldDiff(name, exp, act, False, kind, "validation_fail", f"unknown tolerance {kind!r}")
    except (TypeError, ValueError) as e:
        return FieldDiff(name, exp, act, False, kind, "field_drift", f"{type(e).__name__}: {e}")
    return FieldDiff(name, exp, act, ok, kind, "pass" if ok else "field_drift")


def _is_null(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, list | dict) and not v)


def _norm_str(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().lower()


def _to_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(str(v).strip()[:10], fmt).date()
        except ValueError:
            continue
    return None
