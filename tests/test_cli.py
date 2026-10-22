"""The two commands the README tells you to run, end to end."""
from __future__ import annotations

import json
from pathlib import Path

from supply_pipeline.evals import run as eval_run
from supply_pipeline.readers import tceq_rules
from supply_pipeline.snapshot import __main__ as snapshot

ROOT = Path(__file__).resolve().parent.parent


def test_snapshot_command_is_deterministic(tmp_path):
    out1, out2 = tmp_path / "a.json", tmp_path / "b.json"
    assert snapshot.main(["--sample", str(ROOT / "sample"), "--out", str(out1), "--pgdata", str(tmp_path / "pg")]) == 0
    assert snapshot.main(["--sample", str(ROOT / "sample"), "--out", str(out2), "--pgdata", str(tmp_path / "pg")]) == 0
    assert out1.read_text() == out2.read_text()
    d = json.loads(out1.read_text())
    assert d["headline"]["tracked_feeds"] == 254 and d["generated_at"] == "2026-10-21T12:45:00+00:00"


def test_eval_command_writes_the_site_row(tmp_path):
    code = eval_run.main(["--surface", "azdeq_classify", "--replay",
                          str(ROOT / "data/recorded/azdeq_classify_haiku-4-5_2026-10-03.jsonl"),
                          "--out", str(tmp_path), "--run-at", "2026-10-03T00:00:00+00:00",
                          "--call-log", str(tmp_path / "calls.jsonl")])
    assert code == 1                                     # 7 business misses fail the run, as in production
    summary = json.loads((tmp_path / "eval_azdeq_classify.json").read_text())
    assert summary["site_row"] == {"metro": "Phoenix", "n": 65, "exact": "84.6%", "exactN": 55,
                                   "bucket": "86.2%", "bucketN": 56, "miss": 7}
    assert len((tmp_path / "calls.jsonl").read_text().splitlines()) == 65   # every call logged, $0
    # the committed report is the same run
    committed = json.loads((ROOT / "reports/eval_azdeq_classify.json").read_text())
    assert committed["site_row"] == summary["site_row"]


def test_tceq_model_fallback_only_for_undecided_rows():
    class P:
        model, calls = "m", 0

        def complete(self, req, **kw):
            P.calls += 1
            from supply_pipeline.llm.provider import Completion, Usage
            return Completion("Townhome", Usage())
    decided = {"project_name": "CEDAR TOWNHOMES", "operator_name": "", "construction_type": "",
               "primary_sic_code": "", "disturbed_acres": None}
    undecided = {"project_name": "SOME PROJECT", "operator_name": "X", "construction_type": "",
                 "primary_sic_code": "1522", "disturbed_acres": 2.0}
    assert tceq_rules.classify(P(), decided) == "townhome" and P.calls == 0
    assert tceq_rules.classify(P(), undecided) == "townhome" and P.calls == 1
