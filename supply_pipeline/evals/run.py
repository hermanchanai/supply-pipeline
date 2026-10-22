"""python -m supply_pipeline.evals.run --surface azdeq_classify --replay <recording.jsonl> --out reports

  --replay FILE   answer from a recorded run (no API call, $0)
  --live          call the real model (requirements-live.txt, ANTHROPIC_API_KEY, LLM_MODEL
                  optional); capped at policy.MAX_USD_PER_RUN

Writes <out>/eval_<surface>.md and .json. Exit code: 0 pass, 1 business_miss or hard
regression, 2 setup error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from ..llm.budget import BudgetGuard
from ..llm.provider import AnthropicProvider, CallLog, ReplayProvider
from . import corpus
from .policy import CLASSIFIER_SURFACES, MAX_USD_PER_RUN
from .report import process_classifier_run, render_markdown
from .runner import import_surface, run_classifier_against_goldens

METRO = {"azdeq_classify": "Phoenix", "epd_classify_dwelling": "Atlanta", "epd_classify_enriched": "Atlanta"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--surface", required=True, choices=sorted(CLASSIFIER_SURFACES))
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--replay", type=Path)
    src.add_argument("--live", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("reports"))
    ap.add_argument("--run-at", help="ISO timestamp to stamp the report with (reproducible output)")
    ap.add_argument("--call-log", type=Path, default=Path("data/local/llm_calls.jsonl"))
    args = ap.parse_args(argv)

    golden_surface = CLASSIFIER_SURFACES[args.surface].get("golden_surface", args.surface)
    goldens = corpus.load_classifier_goldens(golden_surface)
    if not goldens:
        print(f"no goldens for {golden_surface}", file=sys.stderr)
        return 2
    mod, _ = import_surface(args.surface)
    model = os.environ.get("LLM_MODEL") or mod.MODEL
    log = CallLog(args.call_log)
    note = ""
    if args.replay:
        provider = ReplayProvider(args.replay, model=model, log=log)
        note = f"Replayed from `{args.replay.name}`: recorded model outputs, no API call."
    else:
        provider = AnthropicProvider(model=model, guard=BudgetGuard(max_run_usd=MAX_USD_PER_RUN), log=log)

    summary = run_classifier_against_goldens(args.surface, goldens, provider)
    run_at = datetime.fromisoformat(args.run_at) if args.run_at else datetime.now(UTC)
    p = process_classifier_run(summary, baseline=corpus.baseline_for(args.surface), run_at=run_at)
    args.out.mkdir(parents=True, exist_ok=True)
    md = render_markdown(p, note=note)
    (args.out / f"eval_{args.surface}.md").write_text(md)
    (args.out / f"eval_{args.surface}.json").write_text(json.dumps(
        {**p.summary(), "site_row": p.site_row(METRO[args.surface]), "failures": p.failures}, indent=2) + "\n")
    print(md)
    return p.exit_code


if __name__ == "__main__":
    sys.exit(main())
