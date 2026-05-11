"""Tests for the @tool decorator and ToolSpec."""

from __future__ import annotations

import pytest

from reigner.harness.state import ToolSpec as ToolSpecProtocol
from reigner.tools.base import ToolDefinitionError, ToolSpec, tool

# ---------------------------------------------------------------------------
# Happy-path: decoration produces a usable ToolSpec
# ---------------------------------------------------------------------------


async def test_decorates_async_function_attaches_spec() -> None:
    @tool(readonly=True)
    async def get_thing(thing_id: str) -> dict:
        """Fetch a thing."""
        return {"id": thing_id}

    spec = get_thing.__reigner_spec__
    assert isinstance(spec, ToolSpec)
    assert spec.name == "get_thing"
    assert spec.description == "Fetch a thing."
    assert spec.readonly is True
    assert spec.pseudo is False
    assert spec.cache is False
    assert spec.truncate_chars is None


async def test_decorated_function_still_directly_callable() -> None:
    @tool(readonly=True)
    async def add(a: int, b: int) -> dict:
        """Add two ints."""
        return {"sum": a + b}

    result = await add(a=2, b=3)
    assert result == {"sum": 5}


async def test_description_defaults_to_docstring_dedented() -> None:
    @tool(readonly=True)
    async def long_doc(x: int) -> dict:
        """First line.

        Second line.
        """
        return {"x": x}

    spec = long_doc.__reigner_spec__
    assert spec.description == "First line.\n\nSecond line."


async def test_description_kwarg_overrides_docstring() -> None:
    @tool(readonly=True, description="custom description")
    async def f(x: int) -> dict:
        """ignored"""
        return {}

    assert f.__reigner_spec__.description == "custom description"


async def test_description_empty_when_no_docstring() -> None:
    @tool(readonly=True)
    async def f(x: int) -> dict:
        return {}

    assert f.__reigner_spec__.description == ""


async def test_flags_pass_through() -> None:
    @tool(readonly=True, cache=True, truncate_chars=8000)
    async def f(x: int) -> dict:
        return {}

    spec = f.__reigner_spec__
    assert spec.cache is True
    assert spec.truncate_chars == 8000


# ---------------------------------------------------------------------------
# JSON Schema generation
# ---------------------------------------------------------------------------


async def test_schema_includes_all_params() -> None:
    @tool(readonly=True)
    async def f(name: str, count: int, active: bool) -> dict:
        return {}

    schema = f.__reigner_spec__.json_schema()
    props = schema["properties"]
    assert set(props.keys()) == {"name", "count", "active"}
    assert props["name"]["type"] == "string"
    assert props["count"]["type"] == "integer"
    assert props["active"]["type"] == "boolean"
    assert set(schema["required"]) == {"name", "count", "active"}


async def test_schema_marks_params_with_defaults_optional() -> None:
    @tool(readonly=True)
    async def f(required: str, optional: int = 5) -> dict:
        return {}

    schema = f.__reigner_spec__.json_schema()
    assert schema["required"] == ["required"]
    assert schema["properties"]["optional"]["default"] == 5


async def test_schema_handles_list_and_optional() -> None:
    @tool(readonly=True)
    async def f(names: list[str], maybe: str | None = None) -> dict:
        return {}

    schema = f.__reigner_spec__.json_schema()
    assert schema["properties"]["names"]["type"] == "array"
    assert schema["properties"]["names"]["items"]["type"] == "string"


# ---------------------------------------------------------------------------
# ToolSpec.call invokes the wrapped function
# ---------------------------------------------------------------------------


async def test_spec_call_invokes_function() -> None:
    @tool(readonly=True)
    async def echo(value: str) -> dict:
        return {"value": value}

    result = await echo.__reigner_spec__.call(value="hi")
    assert result == {"value": "hi"}


async def test_spec_call_propagates_exceptions() -> None:
    @tool(readonly=True)
    async def boom(x: int) -> dict:
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError, match="nope"):
        await boom.__reigner_spec__.call(x=1)


# ---------------------------------------------------------------------------
# Validation: decoration-time rejections
# ---------------------------------------------------------------------------


def test_rejects_sync_function() -> None:
    with pytest.raises(ToolDefinitionError, match="must be `async def`"):

        @tool(readonly=True)
        def sync_tool(x: int) -> dict:  # type: ignore[misc]
            return {}


def test_rejects_var_keyword() -> None:
    with pytest.raises(ToolDefinitionError, match=r"\*\*"):

        @tool(readonly=True)
        async def bad(**kwargs: object) -> dict:
            return {}


def test_rejects_var_positional() -> None:
    with pytest.raises(ToolDefinitionError, match=r"\*"):

        @tool(readonly=True)
        async def bad(*args: object) -> dict:
            return {}


def test_rejects_positional_only() -> None:
    with pytest.raises(ToolDefinitionError, match="positional-only"):

        @tool(readonly=True)
        async def bad(x: int, /) -> dict:
            return {}


def test_rejects_missing_annotation() -> None:
    with pytest.raises(ToolDefinitionError, match="missing a type annotation"):

        @tool(readonly=True)
        async def bad(x) -> dict:  # type: ignore[no-untyped-def]
            return {}


def test_rejects_pseudo_without_readonly() -> None:
    with pytest.raises(ToolDefinitionError, match="pseudo=True requires readonly=True"):

        @tool(pseudo=True, readonly=False)
        async def bad(x: int) -> dict:
            return {}


def test_accepts_pseudo_with_readonly() -> None:
    @tool(pseudo=True, readonly=True)
    async def fine(reason: str) -> dict:
        return {"reason": reason}

    spec = fine.__reigner_spec__
    assert spec.pseudo is True
    assert spec.readonly is True


# ---------------------------------------------------------------------------
# Structural Protocol match against T-03's harness.state.ToolSpec
# ---------------------------------------------------------------------------


async def test_spec_satisfies_state_toolspec_protocol() -> None:
    """T-03's AgentState.tools is list[ToolSpec] where ToolSpec is a
    runtime_checkable Protocol. T-07's concrete ToolSpec must satisfy it
    structurally so AgentState can consume our specs without conversion.
    """

    @tool(readonly=True)
    async def f(x: int) -> dict:
        """doc"""
        return {}

    spec = f.__reigner_spec__
    assert isinstance(spec, ToolSpecProtocol)
