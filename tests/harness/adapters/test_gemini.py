"""GeminiAdapter tests with the SDK mocked."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from reigner.harness.adapters.base import ModelAdapter
from reigner.harness.adapters.gemini import GeminiAdapter
from reigner.harness.state import Prompt, Turn

from .conftest import FakeTool


def _install_fake_client(adapter: GeminiAdapter, response: Any) -> MagicMock:
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=response)
    adapter._client = client
    return client


def test_protocol_conformance() -> None:
    adapter = GeminiAdapter(model="gemini-test")
    assert isinstance(adapter, ModelAdapter)
    assert adapter.name == "gemini"
    assert adapter.supports_prompt_caching is False


async def test_call_translates_system_and_tools(prompt: Prompt, tool: FakeTool) -> None:
    adapter = GeminiAdapter(model="gemini-test")
    response = MagicMock(
        candidates=[
            MagicMock(
                content=MagicMock(parts=[MagicMock(text="ok", function_call=None)]),
                finish_reason="STOP",
            )
        ],
        usage_metadata=MagicMock(
            prompt_token_count=8,
            candidates_token_count=1,
            total_token_count=9,
            cached_content_token_count=0,
        ),
    )
    client = _install_fake_client(adapter, response)

    action = await adapter.call(prompt, [tool])

    payload = client.aio.models.generate_content.await_args.kwargs
    assert payload["model"] == "gemini-test"
    assert payload["config"]["system_instruction"] == prompt.stable
    fdecl = payload["config"]["tools"][0]["function_declarations"][0]
    assert fdecl["name"] == "get_weather"
    assert "additionalProperties" not in fdecl["parameters"]
    assert payload["contents"] == [
        {"role": "user", "parts": [{"text": "What is the weather in Paris?"}]}
    ]

    assert action.is_final_answer is True
    assert action.text == "ok"
    assert action.stop_reason == "end_turn"
    assert action.usage.prompt == 8


async def test_call_parses_function_call(prompt: Prompt, tool: FakeTool) -> None:
    adapter = GeminiAdapter()
    fc = MagicMock(name="get_weather", args={"location": "Paris"}, id=None)
    # MagicMock's `name` collides with the constructor; set it explicitly.
    fc.name = "get_weather"
    response = MagicMock(
        candidates=[
            MagicMock(
                content=MagicMock(parts=[MagicMock(function_call=fc, text=None)]),
                finish_reason="STOP",
            )
        ],
        usage_metadata=None,
    )
    _install_fake_client(adapter, response)

    action = await adapter.call(prompt, [tool])

    assert action.is_final_answer is False
    assert action.stop_reason == "tool_calls"
    assert action.tool_calls[0].name == "get_weather"
    assert action.tool_calls[0].args == {"location": "Paris"}
    # Gemini doesn't return a call id; the adapter synthesises one.
    assert action.tool_calls[0].id.startswith("gemini-get_weather-")


async def test_turn_history_translates_function_response(tool: FakeTool) -> None:
    adapter = GeminiAdapter()
    prompt = Prompt(
        stable="role",
        dynamic_context={},
        messages=[
            Turn(role="user", content="hi"),
            Turn(
                role="assistant",
                content="",
                tool_calls=[{"id": "g-1", "name": "get_weather", "args": {"location": "P"}}],
            ),
            Turn(role="tool", content='{"temp": 18}', tool_call_id="g-1"),
        ],
    )
    response = MagicMock(candidates=[], usage_metadata=None)
    client = _install_fake_client(adapter, response)

    await adapter.call(prompt, [tool])
    contents = client.aio.models.generate_content.await_args.kwargs["contents"]

    assert contents[1]["role"] == "model"
    assert contents[1]["parts"][-1] == {
        "function_call": {"name": "get_weather", "args": {"location": "P"}}
    }
    # function_response on the tool turn is keyed by the tool name (resolved
    # from prior history), not by call_id — that's Gemini's contract.
    assert contents[2] == {
        "role": "user",
        "parts": [
            {
                "function_response": {
                    "name": "get_weather",
                    "response": {"content": '{"temp": 18}'},
                }
            }
        ],
    }
