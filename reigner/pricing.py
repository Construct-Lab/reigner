"""Static per-model token pricing and a pure cost function.

Provider APIs return token counts, never dollars, so cost is computed locally
from a rate table. Rates are USD per 1M tokens; ``cost_usd`` returns ``None``
for a model not in the table so callers can omit the figure rather than show a
wrong one.

Rate provenance (re-verify on model/pricing changes):

- Anthropic — the Claude model reference. Cache reads bill at ~0.1x input and
  cache writes (5-min TTL) at ~1.25x input.
- OpenAI / Google — the providers' published pricing pages (checked 2026-07).
  Neither charges a separate per-token cache *write*, so ``cache_write`` is 0.

Known approximations (see docs/plan/chat-run-cost.html → Future scope):

- Claude Sonnet 5 is under introductory pricing ($2/$10) through 2026-08-31;
  this table carries the standard $3/$15, so cost is a slight over-estimate
  during the intro window rather than a date-branch inside ``cost_usd``.
"""

from __future__ import annotations

from dataclasses import dataclass

from reigner.harness.adapters.base import TokenUsage


@dataclass(frozen=True)
class Rates:
    """USD per 1M tokens for one model."""

    input: float
    output: float
    cache_read: float
    cache_write: float


# Keyed by the model id the adapter is configured with (``model.name`` in
# reigner.yaml). Unknown ids fall through to ``None`` in ``cost_usd``.
PRICES: dict[str, Rates] = {
    # -- Anthropic (Claude model reference) --
    "claude-opus-4-8": Rates(input=5.0, output=25.0, cache_read=0.5, cache_write=6.25),
    "claude-opus-4-7": Rates(input=5.0, output=25.0, cache_read=0.5, cache_write=6.25),
    "claude-sonnet-5": Rates(input=3.0, output=15.0, cache_read=0.3, cache_write=3.75),
    "claude-sonnet-4-6": Rates(input=3.0, output=15.0, cache_read=0.3, cache_write=3.75),
    "claude-haiku-4-5": Rates(input=1.0, output=5.0, cache_read=0.1, cache_write=1.25),
    "claude-fable-5": Rates(input=10.0, output=50.0, cache_read=1.0, cache_write=12.5),
    # -- OpenAI (published pricing, checked 2026-07) --
    "gpt-5.5": Rates(input=5.0, output=30.0, cache_read=0.5, cache_write=0.0),
    # -- Google (Gemini API pricing, checked 2026-07) --
    "gemini-3-pro": Rates(input=2.0, output=12.0, cache_read=0.2, cache_write=0.0),
    "gemini-3-flash": Rates(input=0.5, output=3.0, cache_read=0.05, cache_write=0.0),
}


def cost_usd(usage: TokenUsage, model_id: str) -> float | None:
    """Dollar cost of a :class:`TokenUsage`, or ``None`` if the model is unknown.

    ``usage.prompt`` is the fresh (non-cached) input; cache reads/writes are
    billed separately at their own rates (see the adapters, which normalise
    every provider onto this split). Zeroed usage costs ``0.0``.
    """
    rates = PRICES.get(model_id)
    if rates is None:
        return None
    return (
        usage.prompt * rates.input
        + usage.completion * rates.output
        + usage.cache_read * rates.cache_read
        + usage.cache_write * rates.cache_write
    ) / 1_000_000


__all__ = ["PRICES", "Rates", "cost_usd"]
