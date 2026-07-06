"""AnthropicAdapter tests with the SDK mocked."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from reigner.harness.adapters.anthropic import AnthropicAdapter
from reigner.harness.adapters.base import (
    AdapterAuthError,
    AdapterRateLimitError,
    ModelAdapter,
)
from reigner.harness.state import Prompt, Turn

from .conftest import FakeTool


def _install_fake_client(adapter: AnthropicAdapter, response: Any) -> MagicMock:
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    adapter._client = client
    return client


def test_protocol_conformance() -> None:
    adapter = AnthropicAdapter(model="claude-test")
    assert isinstance(adapter, ModelAdapter)
    assert adapter.name == "anthropic"
    assert adapter.supports_prompt_caching is True


async def test_call_marks_stable_as_cacheable(prompt: Prompt, tool: FakeTool) -> None:
    adapter = AnthropicAdapter(model="claude-test")
    response = MagicMock(
        content=[MagicMock(type="text", text="ok")],
        stop_reason="end_turn",
        usage=MagicMock(
            input_tokens=5,
            output_tokens=2,
            cache_read_input_tokens=100,
            cache_creation_input_tokens=0,
        ),
        id="msg_1",
    )
    client = _install_fake_client(adapter, response)
    action = await adapter.call(prompt, [tool])

    payload = client.messages.create.await_args.kwargs
    assert payload["model"] == "claude-test"
    assert payload["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert payload["system"][0]["text"] == prompt.stable
    assert payload["tools"][0]["input_schema"]["type"] == "object"
    assert "parameters" not in payload["tools"][0]
    assert payload["messages"] == [{"role": "user", "content": "What is the weather in Paris?"}]

    assert action.is_final_answer is True
    assert action.text == "ok"
    assert action.usage.cached == 100
    assert action.usage.prompt == 5
    # Cache reads and writes are split so cost can bill them at distinct rates.
    assert action.usage.cache_read == 100
    assert action.usage.cache_write == 0


async def test_usage_splits_cache_read_and_write(prompt: Prompt, tool: FakeTool) -> None:
    adapter = AnthropicAdapter(model="claude-test")
    response = MagicMock(
        content=[MagicMock(type="text", text="ok")],
        stop_reason="end_turn",
        usage=MagicMock(
            input_tokens=5,
            output_tokens=2,
            cache_read_input_tokens=40,
            cache_creation_input_tokens=10,
        ),
        id="msg_1",
    )
    _install_fake_client(adapter, response)
    action = await adapter.call(prompt, [tool])

    assert action.usage.prompt == 5  # fresh input, cache excluded
    assert action.usage.cache_read == 40
    assert action.usage.cache_write == 10
    assert action.usage.cached == 50


async def test_call_parses_tool_use(prompt: Prompt, tool: FakeTool) -> None:
    adapter = AnthropicAdapter()
    tu = MagicMock(type="tool_use", id="toolu_abc", input={"location": "Paris"})
    tu.name = "get_weather"  # MagicMock's name kwarg sets the mock name.
    response = MagicMock(content=[tu], stop_reason="tool_use", usage=None, id="msg")
    _install_fake_client(adapter, response)
    action = await adapter.call(prompt, [tool])

    assert action.is_final_answer is False
    assert action.stop_reason == "tool_calls"
    assert action.tool_calls[0].id == "toolu_abc"
    assert action.tool_calls[0].name == "get_weather"
    assert action.tool_calls[0].args == {"location": "Paris"}


async def test_turn_history_translates_tool_blocks(tool: FakeTool) -> None:
    adapter = AnthropicAdapter()
    prompt = Prompt(
        stable="role",
        dynamic_context={},
        messages=[
            Turn(role="user", content="weather?"),
            Turn(
                role="assistant",
                content="",
                tool_calls=[{"id": "toolu_1", "name": "get_weather", "args": {"location": "P"}}],
            ),
            Turn(role="tool", content='{"temp": 18}', tool_call_id="toolu_1"),
        ],
    )
    response = MagicMock(content=[], stop_reason="end_turn", usage=None, id="x")
    client = _install_fake_client(adapter, response)

    await adapter.call(prompt, [tool])
    msgs = client.messages.create.await_args.kwargs["messages"]
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"][0] == {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "get_weather",
        "input": {"location": "P"},
    }
    assert msgs[2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"temp": 18}'}],
    }


async def test_error_mapping(prompt: Prompt) -> None:
    pytest.importorskip("anthropic")
    import anthropic

    adapter = AnthropicAdapter()
    for exc_cls, expected in [
        (anthropic.RateLimitError, AdapterRateLimitError),
        (anthropic.AuthenticationError, AdapterAuthError),
    ]:
        err = exc_cls.__new__(exc_cls)
        Exception.__init__(err, "x")
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=err)
        adapter._client = client
        with pytest.raises(expected):
            await adapter.call(prompt, [])
