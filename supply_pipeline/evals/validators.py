"""Cheap checks that run before scoring and cost no tokens."""
from __future__ import annotations

from .policy import CLASSIFIER_VALID_CLASSES

RANGES = {"disturbed_acres": (0.1, 10_000.0), "subdivision_acres": (0.1, 10_000.0),
          "total_lots": (1, 20_000), "latitude": (-90.0, 90.0), "longitude": (-180.0, 180.0)}
MSA_BBOXES = {
    "atlanta": {"lat": (32.5, 35.5), "lon": (-85.5, -82.5)},
    "phoenix": {"lat": (32.5, 34.5), "lon": (-113.0, -110.5)},
    "houston": {"lat": (29.0, 31.0), "lon": (-96.5, -94.5)},
    "austin": {"lat": (29.5, 31.5), "lon": (-98.5, -97.0)},
    "charlotte": {"lat": (34.5, 36.5), "lon": (-81.5, -80.0)},
}


def validate_classifier_output(actual) -> list[str]:
    if actual is None or str(actual).strip() == "":
        return ["classifier returned empty/null"]
    norm = str(actual).strip().lower().replace(" ", "_").replace("-", "_")
    return [] if norm in CLASSIFIER_VALID_CLASSES else [f"classifier output {actual!r} not in enum"]


def validate_extractor_output(actual: dict, msa: str | None = None) -> list[str]:
    errs = []
    if not isinstance(actual, dict) or not actual:
        return ["extractor returned nothing"]
    if all(v in (None, "", [], {}) for v in actual.values()):
        errs.append("every field is empty")
    for k, (lo, hi) in RANGES.items():
        v = actual.get(k)
        if v is None:
            continue
        try:
            if not lo <= float(v) <= hi:
                errs.append(f"{k}={v} outside [{lo}, {hi}]")
        except (TypeError, ValueError):
            errs.append(f"{k}={v!r} is not numeric")
    box = MSA_BBOXES.get(msa or "")
    lat, lon = actual.get("latitude"), actual.get("longitude")
    if box and lat is not None and lon is not None:
        if not (box["lat"][0] <= float(lat) <= box["lat"][1] and box["lon"][0] <= float(lon) <= box["lon"][1]):
            errs.append(f"({lat}, {lon}) outside the {msa} bounding box")
    return errs
