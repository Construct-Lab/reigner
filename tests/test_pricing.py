"""Tests for the static pricing table and cost function."""

from __future__ import annotations

import pytest

from reigner.harness.adapters.base import TokenUsage
from reigner.pricing import PRICES, cost_usd


def test_unknown_model_returns_none() -> None:
    usage = TokenUsage(prompt=1000, completion=1000, total=2000)
    assert cost_usd(usage, "no-such-model") is None


def test_zeroed_usage_costs_nothing() -> None:
    assert cost_usd(TokenUsage.empty(), "claude-opus-4-8") == 0.0


def test_fresh_input_and_output_priced_at_their_rates() -> None:
    # 1M fresh input + 1M output on Opus 4.8 ($5 in / $25 out).
    usage = TokenUsage(prompt=1_000_000, completion=1_000_000, total=2_000_000)
    assert cost_usd(usage, "claude-opus-4-8") == pytest.approx(30.0)


def test_cache_read_and_write_bill_at_distinct_rates() -> None:
    # 1M cache-read + 1M cache-write on Opus 4.8 ($0.5 read / $6.25 write) —
    # the whole point of splitting the field.
    usage = TokenUsage(
        cache_read=1_000_000,
        cache_write=1_000_000,
        cached=2_000_000,
        total=2_000_000,
    )
    assert cost_usd(usage, "claude-opus-4-8") == pytest.approx(0.5 + 6.25)


def test_cache_read_is_cheaper_than_fresh_input() -> None:
    fresh = cost_usd(TokenUsage(prompt=1_000_000), "claude-opus-4-8")
    cached = cost_usd(TokenUsage(cache_read=1_000_000, cached=1_000_000), "claude-opus-4-8")
    assert fresh is not None and cached is not None
    assert cached < fresh


def test_openai_and_gemini_have_no_cache_write_charge() -> None:
    for model in ("gpt-5.5", "gemini-3-pro", "gemini-3-flash"):
        assert PRICES[model].cache_write == 0.0


def test_all_families_present() -> None:
    for model in (
        "claude-opus-4-8",
        "claude-sonnet-5",
        "claude-haiku-4-5",
        "claude-fable-5",
        "gpt-5.5",
        "gemini-3-pro",
        "gemini-3-flash",
    ):
        assert model in PRICES
