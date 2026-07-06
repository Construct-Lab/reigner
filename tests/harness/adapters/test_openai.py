"""OpenAIAdapter tests with the SDK fully mocked.

The Responses API client is replaced with a fake that captures the payload
and returns a scripted response. No network, no real `openai` package
behavior beyond the imported error classes.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from reigner.harness.adapters.base import (
    AdapterAuthError,
    AdapterRateLimitError,
    ModelAdapter,
    TransientAdapterError,
)
from reigner.harness.adapters.openai import OpenAIAdapter
from reigner.harness.state import Prompt, Turn

from .conftest import FakeTool


def _install_fake_client(adapter: OpenAIAdapter, response: Any) -> MagicMock:
    client = MagicMock()
    client.responses.create = AsyncMock(return_value=response)
    adapter._client = client
    return client


def test_protocol_conformance() -> None:
    adapter = OpenAIAdapter(model="gpt-test")
    assert isinstance(adapter, ModelAdapter)
    assert adapter.name == "openai"
    assert adapter.supports_prompt_caching is True


async def test_call_translates_prompt_and_tools(prompt: Prompt, tool: FakeTool) -> None:
    adapter = OpenAIAdapter(model="gpt-test")
    usage = MagicMock(input_tokens=10, output_tokens=2, total_tokens=12, input_tokens_details=None)
    response = MagicMock(
        output=[MagicMock(type="message", content=[MagicMock(type="output_text", text="hi")])],
        usage=usage,
        id="resp_1",
    )
    client = _install_fake_client(adapter, response)

    action = await adapter.call(prompt, [tool])

    client.responses.create.assert_awaited_once()
    payload = client.responses.create.await_args.kwargs
    assert payload["model"] == "gpt-test"
    assert payload["instructions"] == prompt.stable
    assert payload["input"] == [{"role": "user", "content": "What is the weather in Paris?"}]
    assert payload["tool_choice"] == "auto"
    assert payload["tools"][0]["name"] == "get_weather"
    assert payload["tools"][0]["parameters"]["type"] == "object"

    assert action.is_final_answer is True
    assert action.text == "hi"
    assert action.tool_calls == []
    assert action.stop_reason == "end_turn"
    assert action.usage.prompt == 10
    assert action.usage.completion == 2


async def test_usage_subtracts_cached_from_prompt(prompt: Prompt, tool: FakeTool) -> None:
    adapter = OpenAIAdapter(model="gpt-test")
    usage = MagicMock(
        input_tokens=10,
        output_tokens=2,
        total_tokens=12,
        input_tokens_details=MagicMock(cached_tokens=4),
    )
    response = MagicMock(
        output=[MagicMock(type="message", content=[MagicMock(type="output_text", text="hi")])],
        usage=usage,
        id="resp_1",
    )
    _install_fake_client(adapter, response)
    action = await adapter.call(prompt, [tool])

    # OpenAI folds cached tokens into input_tokens; prompt is the fresh remainder.
    assert action.usage.prompt == 6
    assert action.usage.cache_read == 4
    assert action.usage.cache_write == 0
    assert action.usage.cached == 4


async def test_call_parses_tool_call(prompt: Prompt, tool: FakeTool) -> None:
    adapter = OpenAIAdapter()
    fc_item = MagicMock(
        type="function_call",
        call_id="call_abc",
        arguments='{"location": "Paris"}',
    )
    fc_item.name = "get_weather"  # MagicMock's name kwarg sets the mock name, not the attribute.
    response = MagicMock(output=[fc_item], usage=None, id="resp_2")
    _install_fake_client(adapter, response)

    action = await adapter.call(prompt, [tool])

    assert action.is_final_answer is False
    assert action.text is None
    assert action.stop_reason == "tool_calls"
    assert len(action.tool_calls) == 1
    tc = action.tool_calls[0]
    assert tc.id == "call_abc"
    assert tc.name == "get_weather"
    assert tc.args == {"location": "Paris"}


async def test_turn_history_threads_tool_call_and_result(tool: FakeTool) -> None:
    adapter = OpenAIAdapter()
    prompt = Prompt(
        stable="role",
        dynamic_context={},
        messages=[
            Turn(role="user", content="weather in paris?"),
            Turn(
                role="assistant",
                content="",
                tool_calls=[{"id": "c1", "name": "get_weather", "args": {"location": "Paris"}}],
            ),
            Turn(role="tool", content='{"temp": 18}', tool_call_id="c1"),
        ],
    )
    response = MagicMock(output=[], usage=None, id="r")
    client = _install_fake_client(adapter, response)

    await adapter.call(prompt, [tool])
    items = client.responses.create.await_args.kwargs["input"]

    assert items[0] == {"role": "user", "content": "weather in paris?"}
    assert items[1] == {
        "type": "function_call",
        "call_id": "c1",
        "name": "get_weather",
        "arguments": '{"location":"Paris"}',
    }
    assert items[2] == {"type": "function_call_output", "call_id": "c1", "output": '{"temp": 18}'}


async def test_invalid_tool_args_preserved_as_raw(prompt: Prompt, tool: FakeTool) -> None:
    adapter = OpenAIAdapter()
    bad = MagicMock(type="function_call", call_id="c", arguments="not-json")
    bad.name = "t"
    response = MagicMock(output=[bad], usage=None, id="r")
    _install_fake_client(adapter, response)
    action = await adapter.call(prompt, [tool])
    assert action.tool_calls[0].args == {"_raw_arguments": "not-json"}


async def test_error_mapping_rate_limit(prompt: Prompt) -> None:
    pytest.importorskip("openai")
    import openai

    adapter = OpenAIAdapter()
    err = openai.RateLimitError.__new__(openai.RateLimitError)
    Exception.__init__(err, "throttled")
    client = MagicMock()
    client.responses.create = AsyncMock(side_effect=err)
    adapter._client = client

    with pytest.raises(AdapterRateLimitError):
        await adapter.call(prompt, [])


async def test_error_mapping_auth(prompt: Prompt) -> None:
    pytest.importorskip("openai")
    import openai

    adapter = OpenAIAdapter()
    err = openai.AuthenticationError.__new__(openai.AuthenticationError)
    Exception.__init__(err, "bad key")
    client = MagicMock()
    client.responses.create = AsyncMock(side_effect=err)
    adapter._client = client

    with pytest.raises(AdapterAuthError):
        await adapter.call(prompt, [])


async def test_error_mapping_5xx(prompt: Prompt) -> None:
    pytest.importorskip("openai")
    import openai

    adapter = OpenAIAdapter()
    err = openai.APIStatusError.__new__(openai.APIStatusError)
    Exception.__init__(err, "boom")
    err.status_code = 503  # type: ignore[attr-defined]
    client = MagicMock()
    client.responses.create = AsyncMock(side_effect=err)
    adapter._client = client

    with pytest.raises(TransientAdapterError):
        await adapter.call(prompt, [])
