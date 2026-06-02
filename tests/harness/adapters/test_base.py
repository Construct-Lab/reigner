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
    # Strict mode requires additionalProperties: false on every object schema.
    assert out["parameters"]["additionalProperties"] is False


def test_render_openai_strict_promotes_optional_to_required() -> None:
    """Pydantic emits optional `T | None = None` params as anyOf-with-null plus
    `default: null`, and omits them from `required`. OpenAI strict mode rejects
    both — promote everything into required and strip defaults at the boundary."""

    class T(FakeTool):
        def json_schema(self) -> dict:
            return {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "entity": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "default": None,
                    },
                },
                "required": ["query"],
            }

    params = render_tool_for_openai(T())["parameters"]
    assert params["additionalProperties"] is False
    assert set(params["required"]) == {"query", "entity"}
    assert "default" not in params["properties"]["entity"]


def test_render_openai_strict_normalizes_nested_and_defs() -> None:
    """Nested object schemas (including ones reached via ``$defs``) must also
    get ``additionalProperties: false`` and full ``required`` coverage."""

    class T(FakeTool):
        def json_schema(self) -> dict:
            return {
                "type": "object",
                "properties": {
                    "filter": {"$ref": "#/$defs/Filter"},
                },
                "required": ["filter"],
                "$defs": {
                    "Filter": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "value": {"type": "string"},
                        },
                        "required": ["key"],
                    }
                },
            }

    params = render_tool_for_openai(T())["parameters"]
    assert params["additionalProperties"] is False
    filter_def = params["$defs"]["Filter"]
    assert filter_def["additionalProperties"] is False
    assert set(filter_def["required"]) == {"key", "value"}


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
