"""Goldens and baselines read from files (production reads the same rows from tables)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"


@dataclass
class ClassifierGolden:
    id: int
    input_row_id: str
    input_payload: dict
    expected_class: str
    label_method: str
    cohort_tags: dict = field(default_factory=dict)
    valid_through: str | None = None


def load_classifier_goldens(surface: str, *, data_dir: Path = DATA, valid_on: date | None = None) -> list[ClassifierGolden]:
    path = data_dir / "goldens" / f"{surface}.jsonl"
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if valid_on and r.get("valid_through") and date.fromisoformat(r["valid_through"]) < valid_on:
            continue
        out.append(ClassifierGolden(id=r["golden_id"], input_row_id=str(r["input_row_id"]),
                                    input_payload=r["input_payload"], expected_class=r["expected_class"],
                                    label_method=r["label_method"], cohort_tags=r.get("cohort_tags") or {},
                                    valid_through=r.get("valid_through")))
    return out


def baseline_for(surface: str, *, data_dir: Path = DATA) -> dict | None:
    path = data_dir / "eval_baselines.json"
    if not path.exists():
        return None
    return json.loads(path.read_text()).get(surface)
