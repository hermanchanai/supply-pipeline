"""Shared by the readers that write entitlement (pre-permit) cases."""
from __future__ import annotations

import re

COLUMNS = ("msa", "jurisdiction", "source_type", "case_number", "case_type_raw", "stage", "project_name",
           "status_raw", "lifecycle_status", "application_date", "latest_action_date", "land_use_raw",
           "dwelling_type", "units_filed", "lots_filed", "acres", "address", "city", "county",
           "latitude", "longitude", "link", "raw_json")


def classify_dwelling(*texts) -> str:
    """Rule-based dwelling type over any text fields of a case."""
    t = " ".join(str(x).lower() for x in texts if x)
    if re.search(r"multi[- ]?fam|apartment|condominium|\bcondo\b|\bmf\b", t):
        return "multifamily"
    if re.search(r"mixed[- ]?use|\bmixed\b|\bpud\b|planned unit", t):
        return "mixed"
    if re.search(r"town ?home|town ?house", t):
        return "townhome"
    # A subdivision case is single-family lots unless an MF/TH/mixed signal fired above.
    if re.search(r"single[- ]?fam|\bsfr\b|\bsubdivision\b|\bplat\b|\bsf\b(?!t)", t):
        return "single_family"
    return "unknown"


def upsert_cases(store, rows: list[dict]) -> int:
    """Re-sweeps are idempotent. A NULL from a thinner source never wipes a name or unit
    count another process filled, and coordinates only move as a complete pair."""
    full = [{c: r.get(c) for c in COLUMNS} | {"raw_json": r.get("raw_json") or {}} for r in rows]
    return store.upsert("county_permits.entitlement_cases", full, key=("jurisdiction", "case_number"),
                        coalesce=("project_name", "units_filed", "lots_filed", "acres"),
                        coord_pair=("latitude", "longitude"))
