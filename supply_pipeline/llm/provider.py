"""Provider facade: classifiers call `provider.complete(Request(...))` and never touch a
vendor SDK. Three providers:

  AnthropicProvider -- the real API (needs `anthropic` from requirements-live.txt and a key).
  ReplayProvider    -- answers from a recorded file, keyed by a hash of the exact user
                       message, so a re-score costs nothing and cannot drift: a changed
                       prompt input misses the recording and fails loudly.
  (tests use small fakes with the same .complete signature)

Every completed call goes through `CallLog.write` and `BudgetGuard.record`.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import pricing
from .budget import BudgetGuard

CHARS_PER_TOKEN = 4.0


class UnknownModel(ValueError):
    """No verified price row for this model."""


class ReplayMiss(KeyError):
    """The recording has no answer for this exact input."""


@dataclass(frozen=True)
class Request:
    system: str
    user: str
    max_tokens: int
    model: str
    temperature: float | None = None


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class Completion:
    text: str
    usage: Usage
    latency_ms: int | None = None


def user_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def estimate_usd(req: Request) -> float:
    """A ceiling for the spend guard, never a typical cost."""
    p = pricing.PRICES.get(req.model)
    if p is None:
        raise UnknownModel(req.model)
    sys_t = len(req.system) / CHARS_PER_TOKEN
    usr_t = len(req.user) / CHARS_PER_TOKEN
    return (sys_t * max(p.input, p.cache_write) + usr_t * p.input + req.max_tokens * p.output) / 1e6


class CallLog:
    """One JSON line per call: when, which model, which feature, tokens, cost, latency."""

    def __init__(self, path: Path | None):
        self.path = path

    def write(self, *, provider: str, req: Request, feature: str | None, c: Completion,
              cost: float | None) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), "provider": provider,
               "model": req.model, "feature": feature, "user_sha256": user_hash(req.user),
               "usage": asdict(c.usage), "cost_usd": cost, "latency_ms": c.latency_ms}
        with self.path.open("a") as f:
            f.write(json.dumps(row) + "\n")


class ReplayProvider:
    name = "replay"

    def __init__(self, path: Path, *, model: str, log: CallLog | None = None):
        self.model = model
        self.answers: dict[str, str] = {}
        self.meta: dict[str, dict] = {}
        for line in Path(path).read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                self.answers[r["user_sha256"]] = r["output"]
                self.meta[r["user_sha256"]] = r
        self.log = log or CallLog(None)
        self.calls = 0

    def complete(self, req: Request, *, feature: str | None = None, metadata: dict | None = None) -> Completion:
        key = user_hash(req.user)
        if key not in self.answers:
            raise ReplayMiss(f"no recorded answer for this input ({key[:12]}...)")
        self.calls += 1
        c = Completion(text=self.answers[key], usage=Usage(), latency_ms=0)
        self.log.write(provider=self.name, req=req, feature=feature, c=c, cost=0.0)
        return c


class AnthropicProvider:
    """The real Messages API. Imported lazily so the offline install never needs the SDK."""
    name = "anthropic"

    def __init__(self, *, model: str, guard: BudgetGuard | None = None, log: CallLog | None = None,
                 client=None):
        if model not in pricing.PRICES:
            raise UnknownModel(f"no verified price for {model!r}; add it to llm.pricing first")
        if client is None:
            import anthropic  # requirements-live.txt
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.client = client
        self.model = model
        self.guard = guard or BudgetGuard()
        self.log = log or CallLog(None)

    def complete(self, req: Request, *, feature: str | None = None, metadata: dict | None = None) -> Completion:
        self.guard.check(estimate_usd(req))
        params = {"model": req.model, "max_tokens": req.max_tokens,
                  "system": [{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
                  "messages": [{"role": "user", "content": req.user}]}
        if req.temperature is not None:
            params["temperature"] = req.temperature
        t0 = time.perf_counter()
        msg = self.client.messages.create(**params)
        latency = int((time.perf_counter() - t0) * 1000)
        u = msg.usage
        usage = Usage(input_tokens=int(getattr(u, "input_tokens", 0) or 0),
                      output_tokens=int(getattr(u, "output_tokens", 0) or 0),
                      cache_read_tokens=int(getattr(u, "cache_read_input_tokens", 0) or 0),
                      cache_write_tokens=int(getattr(u, "cache_creation_input_tokens", 0) or 0))
        text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "text") == "text")
        cost = pricing.cost_usd(req.model, usage.input_tokens, usage.output_tokens,
                                usage.cache_read_tokens, usage.cache_write_tokens)
        c = Completion(text=text, usage=usage, latency_ms=latency)
        self.guard.record(cost or 0.0)
        self.log.write(provider=self.name, req=req, feature=feature, c=c, cost=cost)
        return c
