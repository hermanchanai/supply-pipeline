"""Spend caps checked BEFORE a call fires.

  per_call -- the projected cost of this one call (a ceiling: system prompt billed as a
              cache write, the user text at input price, max_tokens of output). Trips when
              an estimate is far off, which usually means a prompt bug.
  per_run  -- what this process has actually spent so far plus the projected call.

Over a cap raises BudgetExceeded and the call never happens (fail closed). There is no
fail-open path here because there is no remote budget table to be unreachable.
"""
from __future__ import annotations


class BudgetExceeded(RuntimeError):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class BudgetGuard:
    def __init__(self, *, max_run_usd: float | None = None, max_call_usd: float | None = None):
        self.max_run_usd = max_run_usd
        self.max_call_usd = max_call_usd
        self.spent_usd = 0.0
        self.calls = 0

    def check(self, projected_usd: float) -> None:
        if self.max_call_usd is not None and projected_usd > self.max_call_usd:
            raise BudgetExceeded("per_call", f"projected ${projected_usd:.4f} > per-call cap ${self.max_call_usd:.4f}")
        if self.max_run_usd is not None and self.spent_usd + projected_usd > self.max_run_usd:
            raise BudgetExceeded("per_run", f"spent ${self.spent_usd:.4f} + projected ${projected_usd:.4f} "
                                            f"> run cap ${self.max_run_usd:.2f}")

    def record(self, actual_usd: float) -> None:
        self.spent_usd += actual_usd
        self.calls += 1
