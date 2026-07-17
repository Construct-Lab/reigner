"""Effort knob → provider payload, across all three adapters.

Guards the core contract of issue #136: effort is mapped to each provider's
reasoning key behind a model-capability check, temperature is emitted only when
explicitly set and only on models that accept it, and the default config never
puts `temperature` on the frontier path (which would 400).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from reigner.harness.adapters import build_adapter
from reigner.harness.adapters.anthropic import AnthropicAdapter
from reigner.harness.adapters.gemini import GeminiAdapter
from reigner.harness.adapters.openai import OpenAIAdapter
from reigner.harness.state import Prompt


def _anthropic_response() -> MagicMock:
    return MagicMock(
        content=[MagicMock(type="text", text="ok")],
        stop_reason="end_turn",
        usage=MagicMock(
            input_tokens=1,
            output_tokens=1,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
        id="msg",
    )


def _openai_response() -> MagicMock:
    usage = MagicMock(input_tokens=1, output_tokens=1, total_tokens=2, input_tokens_details=None)
    return MagicMock(
        output=[MagicMock(type="message", content=[MagicMock(type="output_text", text="ok")])],
        usage=usage,
        id="resp",
    )


def _gemini_response() -> MagicMock:
    return MagicMock(
        candidates=[
            MagicMock(
                content=MagicMock(parts=[MagicMock(text="ok", function_call=None)]),
                finish_reason="STOP",
            )
        ],
        usage_metadata=MagicMock(
            prompt_token_count=1,
            candidates_token_count=1,
            total_token_count=2,
            cached_content_token_count=0,
        ),
    )


def _install(adapter: Any, create_path: str, response: Any) -> MagicMock:
    client = MagicMock()
    target = client
    *heads, tail = create_path.split(".")
    for part in heads:
        target = getattr(target, part)
    setattr(target, tail, AsyncMock(return_value=response))
    adapter._client = client
    return client


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


async def test_anthropic_frontier_sends_effort_not_temperature(prompt: Prompt) -> None:
    adapter = AnthropicAdapter(model="claude-opus-4-7", effort="high", temperature=0.9)
    client = _install(adapter, "messages.create", _anthropic_response())

    await adapter.call(prompt, [])

    payload = client.messages.create.await_args.kwargs
    assert payload["output_config"] == {"effort": "high"}
    # Even with temperature explicitly set, it must never ride the frontier path.
    assert "temperature" not in payload


async def test_anthropic_default_config_omits_temperature(prompt: Prompt) -> None:
    # The regression guard: the shipped default (Opus 4.7, no temperature) must
    # build a payload with no `temperature` key, or the provider 400s.
    adapter = build_adapter("anthropic", "claude-opus-4-7")
    assert isinstance(adapter, AnthropicAdapter)
    client = _install(adapter, "messages.create", _anthropic_response())

    await adapter.call(prompt, [])

    payload = client.messages.create.await_args.kwargs
    assert "temperature" not in payload
    assert payload["output_config"] == {"effort": "medium"}


async def test_anthropic_legacy_model_takes_temperature_when_set(prompt: Prompt) -> None:
    adapter = AnthropicAdapter(model="claude-haiku-4-5", effort="high", temperature=0.3)
    client = _install(adapter, "messages.create", _anthropic_response())

    await adapter.call(prompt, [])

    payload = client.messages.create.await_args.kwargs
    assert payload["temperature"] == 0.3
    assert "output_config" not in payload


async def test_anthropic_legacy_model_omits_unset_temperature(prompt: Prompt) -> None:
    adapter = AnthropicAdapter(model="claude-haiku-4-5")
    client = _install(adapter, "messages.create", _anthropic_response())

    await adapter.call(prompt, [])

    payload = client.messages.create.await_args.kwargs
    assert "temperature" not in payload
    assert "output_config" not in payload


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("effort", "expected"),
    [("low", "low"), ("medium", "medium"), ("high", "high"), ("xhigh", "high"), ("max", "high")],
)
async def test_openai_reasoning_maps_effort(prompt: Prompt, effort: str, expected: str) -> None:
    adapter = OpenAIAdapter(model="gpt-5.5", effort=effort, temperature=0.7)  # type: ignore[arg-type]
    client = _install(adapter, "responses.create", _openai_response())

    await adapter.call(prompt, [])

    payload = client.responses.create.await_args.kwargs
    assert payload["reasoning"] == {"effort": expected}
    assert "temperature" not in payload


async def test_openai_chat_model_takes_temperature_when_set(prompt: Prompt) -> None:
    adapter = OpenAIAdapter(model="gpt-4o", effort="high", temperature=0.5)
    client = _install(adapter, "responses.create", _openai_response())

    await adapter.call(prompt, [])

    payload = client.responses.create.await_args.kwargs
    assert payload["temperature"] == 0.5
    assert "reasoning" not in payload


async def test_openai_chat_model_omits_unset_temperature(prompt: Prompt) -> None:
    adapter = OpenAIAdapter(model="gpt-4o")
    client = _install(adapter, "responses.create", _openai_response())

    await adapter.call(prompt, [])

    payload = client.responses.create.await_args.kwargs
    assert "temperature" not in payload
    assert "reasoning" not in payload


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", ["gemini-3-flash-preview", "gemini-3.5-flash"])
async def test_gemini_thinking_models_send_thinking_level(prompt: Prompt, model: str) -> None:
    adapter = GeminiAdapter(model=model, effort="max", temperature=0.9)
    client = _install(adapter, "aio.models.generate_content", _gemini_response())

    await adapter.call(prompt, [])

    config = client.aio.models.generate_content.await_args.kwargs["config"]
    assert config["thinking_config"] == {"thinking_level": "high"}  # max clamps to high
    assert "temperature" not in config


# Gemini 2.5 rejects thinking_level on generateContent (only 3.x accepts it), so
# it behaves like a pre-thinking model here: no effort, temperature if set.
@pytest.mark.parametrize("model", ["gemini-2.0-flash", "gemini-2.5-flash"])
async def test_gemini_non_thinking_model_takes_temperature_when_set(
    prompt: Prompt, model: str
) -> None:
    adapter = GeminiAdapter(model=model, effort="high", temperature=0.4)
    client = _install(adapter, "aio.models.generate_content", _gemini_response())

    await adapter.call(prompt, [])

    config = client.aio.models.generate_content.await_args.kwargs["config"]
    assert config["temperature"] == 0.4
    assert "thinking_config" not in config


async def test_gemini_non_thinking_model_omits_unset_temperature(prompt: Prompt) -> None:
    adapter = GeminiAdapter(model="gemini-2.0-flash")
    client = _install(adapter, "aio.models.generate_content", _gemini_response())

    await adapter.call(prompt, [])

    config = client.aio.models.generate_content.await_args.kwargs["config"]
    assert "temperature" not in config
    assert "thinking_config" not in config


# ---------------------------------------------------------------------------
# Builder threads effort + temperature through
# ---------------------------------------------------------------------------


def test_build_adapter_threads_effort_and_temperature() -> None:
    adapter = build_adapter("openai", "gpt-4o", effort="low", temperature=0.2)
    assert isinstance(adapter, OpenAIAdapter)
    assert adapter.effort == "low"
    assert adapter.temperature == 0.2
