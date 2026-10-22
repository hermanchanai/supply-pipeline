"""LLM wrapper. Spec: an unknown model is refused (never priced at $0); a call that would
breach a cap never fires; replay answers only the exact recorded input; every call is logged."""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from supply_pipeline.llm import pricing
from supply_pipeline.llm.budget import BudgetExceeded, BudgetGuard
from supply_pipeline.llm.provider import (
    AnthropicProvider,
    CallLog,
    ReplayMiss,
    ReplayProvider,
    Request,
    UnknownModel,
    estimate_usd,
    user_hash,
)

REQ = Request(system="s" * 400, user="u" * 400, max_tokens=10, model="claude-haiku-4-5")


def fake_client(text="multifamily", in_tok=120, out_tok=2):
    calls = []

    def create(**kw):
        calls.append(kw)
        return NS(content=[NS(type="text", text=text)],
                  usage=NS(input_tokens=in_tok, output_tokens=out_tok,
                           cache_read_input_tokens=0, cache_creation_input_tokens=0))
    return NS(messages=NS(create=create)), calls


def test_cost_is_exact_and_unknown_model_is_none():
    assert pricing.cost_usd("claude-haiku-4-5", 1_000_000, 1_000_000) == pytest.approx(6.0)
    assert pricing.cost_usd("made-up-model", 10, 10) is None


def test_unknown_model_refused_up_front():
    with pytest.raises(UnknownModel):
        AnthropicProvider(model="made-up-model", client=object())


def test_estimate_is_a_ceiling():
    # system billed at the cache-write rate, user at input, all of max_tokens as output
    assert estimate_usd(REQ) == pytest.approx((100 * 1.25 + 100 * 1.0 + 10 * 5.0) / 1e6)


def test_per_call_cap_blocks_before_the_call():
    client, calls = fake_client()
    p = AnthropicProvider(model="claude-haiku-4-5", client=client, guard=BudgetGuard(max_call_usd=1e-9))
    with pytest.raises(BudgetExceeded) as e:
        p.complete(REQ)
    assert e.value.kind == "per_call" and calls == []


def test_per_run_cap_counts_actual_spend(tmp_path):
    client, calls = fake_client(in_tok=1000, out_tok=100)
    guard = BudgetGuard(max_run_usd=0.0016)
    p = AnthropicProvider(model="claude-haiku-4-5", client=client, guard=guard,
                          log=CallLog(tmp_path / "calls.jsonl"))
    p.complete(REQ, feature="t")          # costs 1000*1 + 100*5 = $0.0015
    assert guard.spent_usd == pytest.approx(0.0015)
    with pytest.raises(BudgetExceeded) as e:
        p.complete(REQ)                   # 0.0015 spent + 0.000275 ceiling > 0.0016
    assert e.value.kind == "per_run" and len(calls) == 1
    row = json.loads((tmp_path / "calls.jsonl").read_text().splitlines()[0])
    assert row["model"] == "claude-haiku-4-5" and row["feature"] == "t"
    assert row["cost_usd"] == pytest.approx(0.0015) and row["user_sha256"] == user_hash(REQ.user)


def test_request_shape_sent_to_the_sdk():
    client, calls = fake_client()
    AnthropicProvider(model="claude-haiku-4-5", client=client).complete(
        Request(system="SYS", user="USER", max_tokens=10, model="claude-haiku-4-5", temperature=0.0))
    kw = calls[0]
    assert kw["system"][0]["text"] == "SYS" and kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["messages"] == [{"role": "user", "content": "USER"}] and kw["temperature"] == 0.0


def test_replay_answers_only_the_exact_input(tmp_path):
    rec = tmp_path / "r.jsonl"
    rec.write_text(json.dumps({"user_sha256": user_hash("hello"), "output": "townhome"}) + "\n")
    p = ReplayProvider(rec, model="claude-haiku-4-5")
    assert p.complete(Request("s", "hello", 10, "claude-haiku-4-5")).text == "townhome"
    with pytest.raises(ReplayMiss):
        p.complete(Request("s", "hello ", 10, "claude-haiku-4-5"))
