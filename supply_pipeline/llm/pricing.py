"""Model prices in USD per 1,000,000 tokens (input, output, cache read, cache write 5m).

Anthropic rows from the published pricing page as checked on 2026-09-22; the OpenAI row
from its pricing page as checked on 2026-09-18. Hard-coded per model on purpose: cache
rates have broken the usual 10% / 125% pattern for some models, and a written table is
easier to audit than a formula. A model missing here prices to None, and the provider
refuses to run it rather than log its spend as $0.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float
    cache_write: float


PRICES: dict[str, Price] = {
    "claude-haiku-4-5": Price(1.0, 5.0, 0.10, 1.25),
    "claude-haiku-4-5-20251001": Price(1.0, 5.0, 0.10, 1.25),
    "claude-sonnet-4-6": Price(3.0, 15.0, 0.30, 3.75),
    "claude-sonnet-5": Price(2.0, 10.0, 0.20, 2.50),
    "claude-opus-4-8": Price(5.0, 25.0, 0.50, 6.25),
    "gpt-5.6-luna": Price(0.20, 1.20, 0.02, 0.25),
}

# Message Batches / Batch API: half price on both vendors.
BATCH_MULTIPLIER = 0.5


def cost_usd(model: str, input_tokens: int, output_tokens: int,
             cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> float | None:
    p = PRICES.get(model)
    if p is None:
        return None
    return (input_tokens * p.input + output_tokens * p.output
            + cache_read_tokens * p.cache_read + cache_write_tokens * p.cache_write) / 1_000_000
