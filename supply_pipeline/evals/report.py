"""Aggregate a run: score each case, roll up rates, compare with the baseline, decide the
exit code, render markdown and a JSON summary (the source for the public page's table)."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime

from .comparator import compare_classifier
from .policy import CALIBRATION_WINDOW_END, business_bucket, regression_thresholds_for

SEVERITY_DESC = (
    ("pass", "exact match"),
    ("cosmetic_miss", "wrong class, same business bucket (SF<->TH): no decision impact"),
    ("business_miss", "crosses for_sale<->rental: corrupts supply counts"),
    ("overcommit", "golden=unknown, model guessed"),
    ("abstain_miss", "golden=confident, model returned unknown"),
    ("validation_fail", "output not in enum"),
)


@dataclass
class ProcessedRun:
    surface: str
    model: str
    provider: str
    run_at: str
    cases_total: int
    cases_passed: int
    pass_rate: float
    bucket_passed: int
    bucket_pass_rate: float
    business_miss: int
    severity_counts: dict
    class_pass_rates: dict
    baseline_pass_rate: float | None
    regression_detected: bool
    alert_severity: str | None
    alert_message: str
    exit_code: int
    cost_usd: float
    failures: list

    def summary(self) -> dict:
        d = asdict(self)
        d.pop("failures")
        return d

    def site_row(self, metro: str) -> dict:
        """The public page's evaluation-table row."""
        return {"metro": metro, "n": self.cases_total,
                "exact": f"{self.pass_rate:.1%}", "exactN": self.cases_passed,
                "bucket": f"{self.bucket_pass_rate:.1%}", "bucketN": self.bucket_passed,
                "miss": self.business_miss}


def process_classifier_run(summary, *, baseline: dict | None, today: date | None = None,
                           run_at: datetime | None = None) -> ProcessedRun:
    today = today or date.today()
    sev = Counter()
    by_class: dict[str, list[bool]] = defaultdict(list)
    confusion: Counter = Counter()
    bucket_flags, failures = [], []
    for r in summary.results:
        if r.error or r.actual_class is None:
            s, passed, bp = "validation_fail", False, False
            eb, ab = business_bucket(r.expected_class), "invalid"
        else:
            c = compare_classifier(r.expected_class, r.actual_class)
            s, passed, bp, eb, ab = c.severity, c.passed, c.bucket_passed, c.expected_bucket, c.actual_bucket
        sev[s] += 1
        by_class[r.expected_class].append(passed)
        confusion[(eb, ab)] += 1
        bucket_flags.append(bp)
        if not passed:
            failures.append({"severity": s, "input_row_id": r.input_row_id, "expected": r.expected_class,
                             "actual": r.actual_class, "error": r.error})

    n = len(summary.results)
    passed_n = sev["pass"]
    rate = passed_n / n if n else 0.0
    bucket_n = sum(bucket_flags)
    bucket_rate = bucket_n / n if n else 0.0
    base_rate = (baseline or {}).get("pass_rate")

    alert, regression, msgs = None, False, []
    warn_drop, hard_drop = regression_thresholds_for(summary.surface)
    if base_rate is not None:
        drop = base_rate - rate
        if drop >= hard_drop:
            alert, regression = "critical", True
            msgs.append(f"pass rate dropped {drop:.1%} (baseline {base_rate:.1%} -> {rate:.1%})")
        elif drop >= warn_drop:
            alert = "warn"
            msgs.append(f"pass rate drop within warn band: {drop:.1%}")
    if sev["business_miss"]:
        alert, regression = "critical", True
        msgs.append(f"{sev['business_miss']} business_miss (crosses for_sale<->rental)")
    soft = sev["overcommit"] + sev["abstain_miss"]
    if soft and alert is None:
        alert = "warn"
        msgs.append(f"{sev['overcommit']} overcommit + {sev['abstain_miss']} abstain_miss")
    in_calibration = today <= CALIBRATION_WINDOW_END
    exit_code = 1 if regression and not in_calibration else 0

    order = {"business_miss": 0, "overcommit": 1, "abstain_miss": 2, "cosmetic_miss": 3, "validation_fail": 4}
    failures.sort(key=lambda f: (order.get(f["severity"], 9), f["input_row_id"]))
    return ProcessedRun(
        surface=summary.surface, model=summary.model, provider=summary.provider,
        run_at=(run_at or datetime.now(UTC)).isoformat(timespec="seconds"),
        cases_total=n, cases_passed=passed_n, pass_rate=round(rate, 4),
        bucket_passed=bucket_n, bucket_pass_rate=round(bucket_rate, 4), business_miss=sev["business_miss"],
        severity_counts={k: sev.get(k, 0) for k, _ in SEVERITY_DESC},
        class_pass_rates={c: round(sum(v) / len(v), 4) for c, v in sorted(by_class.items())},
        baseline_pass_rate=base_rate, regression_detected=regression, alert_severity=alert,
        alert_message="; ".join(msgs), exit_code=exit_code, cost_usd=summary.cost_usd, failures=failures)


def render_markdown(p: ProcessedRun, *, note: str = "") -> str:
    lines = [f"# Eval run: {p.surface}", "",
             f"Model: {p.model} (provider: {p.provider}) | run at {p.run_at}", ""]
    if note:
        lines += [note, ""]
    lines += [
        f"- Strict accuracy: {p.cases_passed}/{p.cases_total} = {p.pass_rate:.1%}",
        f"- Business-bucket accuracy (for sale / rental / mixed / commercial / unknown): "
        f"{p.bucket_passed}/{p.cases_total} = {p.bucket_pass_rate:.1%}",
        f"- Rent / sale errors (business_miss): {p.business_miss}",
        (f"- Baseline (strict): {p.baseline_pass_rate:.1%}" if p.baseline_pass_rate is not None
         else "- Baseline: none"),
        f"- Cost of this run: ${p.cost_usd:.4f}",
        "", "## Severity", ""]
    for s, desc in SEVERITY_DESC:
        lines.append(f"- {s}: {p.severity_counts.get(s, 0)} ({desc})")
    lines += ["", "## Accuracy by golden class", ""]
    for c, rate in p.class_pass_rates.items():
        lines.append(f"- {c}: {rate:.1%}")
    if p.failures:
        lines += ["", f"## Failures ({len(p.failures)})", ""]
        for f in p.failures:
            lines.append(f"- [{f['severity']}] `{f['input_row_id']}` expected={f['expected']!r} "
                         f"actual={f['actual']!r}")
    if p.alert_severity:
        lines += ["", f"## Alert: {p.alert_severity.upper()}", "", p.alert_message]
    lines += ["", f"Exit code: {p.exit_code} "
              "(1 = a business_miss or a hard regression; the calibration window closed 2026-06-22)", ""]
    return "\n".join(lines)
