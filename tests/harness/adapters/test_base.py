"""Tests for the provider-neutral adapter types and translation helpers."""

from __future__ import annotations

from reigner.harness.adapters.base import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimitError,
    ModelAction,
    TokenUsage,
    ToolCall,
    TransientAdapterError,
    render_tool_for_anthropic,
    render_tool_for_gemini,
    render_tool_for_openai,
)

from .conftest import FakeTool


def test_token_usage_empty_defaults() -> None:
    u = TokenUsage.empty()
    assert u.prompt == 0 and u.completion == 0 and u.cached == 0 and u.total == 0


def test_model_action_defaults() -> None:
    a = ModelAction(is_final_answer=True, text="ok")
    assert a.tool_calls == []
    assert a.usage.total == 0
    assert a.stop_reason == "other"


def test_tool_call_frozen() -> None:
    tc = ToolCall(id="abc", name="t", args={"x": 1})
    assert tc.args == {"x": 1}


def test_error_hierarchy() -> None:
    assert issubclass(TransientAdapterError, AdapterError)
    assert issubclass(AdapterRateLimitError, TransientAdapterError)
    assert issubclass(AdapterAuthError, AdapterError)
    assert not issubclass(AdapterAuthError, TransientAdapterError)


def test_render_openai() -> None:
    out = render_tool_for_openai(FakeTool())
    assert out["type"] == "function"
    assert out["name"] == "get_weather"
    assert out["strict"] is True
    assert out["parameters"]["type"] == "object"
    assert out["parameters"]["properties"]["location"]["type"] == "string"


def test_render_anthropic() -> None:
    out = render_tool_for_anthropic(FakeTool())
    assert "parameters" not in out
    assert out["input_schema"]["type"] == "object"
    assert out["name"] == "get_weather"


def test_render_gemini_strips_unsupported() -> None:
    out = render_tool_for_gemini(FakeTool())
    assert out["name"] == "get_weather"
    params = out["parameters"]
    # additionalProperties must be stripped — Gemini's validator rejects it.
    assert "additionalProperties" not in params
    assert params["properties"]["location"]["type"] == "string"


def test_render_gemini_strips_nested() -> None:
    class T(FakeTool):
        def json_schema(self) -> dict:
            return {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "obj": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"k": {"type": "string"}},
                    }
                },
            }

    out = render_tool_for_gemini(T())
    assert "$schema" not in out["parameters"]
    assert "additionalProperties" not in out["parameters"]["properties"]["obj"]
