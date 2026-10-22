"""Load the bundled `sample/` into a store.

sample/ holds, frozen on the date in sample/manifest.json:
  * the feed registry as it stood at the public page's snapshot (254 tracked feeds) and
    each feed's coverage counts;
  * the multifamily permit layer (one row per active project; no names or owners);
  * the candidate rows the per-metro project sample is drawn from;
  * a small slice of public-record rows for each example feed's own table.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

# (file stem = schema.table, conflict key). Order matters for foreign keys.
TABLES: list[tuple[str, tuple[str, ...]]] = [
    ("registry.pipeline_sources", ("id",)),
    ("registry.pipeline_coverage", ("msa", "source_label")),
    ("layers.mf_projects", ("mv_row_id",)),
    ("layers.pipeline_unified", ("canonical_project_id",)),
    ("layers.sfd_projects", ("mv_row_id",)),
    ("layers.entitlement_other", ("jurisdiction", "case_number")),
    ("nashville.building_permits_issued", ("permit_number",)),
    ("nashville.planning_dev_cases", ("ca_object_id",)),
    ("county_permits.entitlement_cases", ("jurisdiction", "case_number")),
    ("tceq.cgp_noi", ("authorization_number",)),
    ("azre.public_reports", ("registration_number",)),
    ("azre.public_reports_extracted", ("registration_number",)),
    ("coa.subdivision_review_cases", ("folderrsn",)),
    ("ncdeq.noi_submissions", ("permit_number",)),
]


def _csv_value(v: str):
    if v == "":
        return None
    if v in ("True", "False"):
        return v == "True"
    try:
        return int(v)
    except ValueError:
        return v


def read_table(sample_dir: Path, stem: str) -> list[dict]:
    jl = sample_dir / f"{stem}.jsonl"
    if jl.exists():
        return [json.loads(line) for line in jl.read_text().splitlines() if line.strip()]
    cs = sample_dir / f"{stem}.csv"
    if cs.exists():
        with cs.open(newline="") as f:
            return [{k: _csv_value(v) for k, v in r.items()} for r in csv.DictReader(f)]
    return []


def manifest(sample_dir: Path) -> dict:
    return json.loads((sample_dir / "manifest.json").read_text())


def load(store, sample_dir: Path) -> dict[str, int]:
    counts = {}
    for stem, key in TABLES:
        rows = read_table(sample_dir, stem)
        counts[stem] = store.upsert(stem, rows, key=key) if rows else 0
    return counts
