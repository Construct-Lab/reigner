"""Tests for RunnableToolAdapter + to_runnable.

The adapter is the single bridge from `@tool`-decorated functions to the
loop's RunnableTool Protocol. It must forward every ToolSpec field flat,
unpack kwargs on `.run(args)`, and refuse non-decorated callables.
"""

from __future__ import annotations

import pytest

from reigner.harness.loop import RunnableTool
from reigner.tools.base import (
    RunnableToolAdapter,
    ToolDefinitionError,
    to_runnable,
    tool,
)


@tool(readonly=True, cache=True, truncate_chars=2048, description="A test tool.")
async def sample_tool(query: str, top_k: int = 3) -> dict:
    return {"query": query, "top_k": top_k}


@tool(readonly=True, pseudo=True)
async def sample_pseudo(token: str) -> dict:
    return {"token": token}


def test_adapter_forwards_every_tool_spec_field() -> None:
    adapter = to_runnable(sample_tool)

    assert adapter.name == "sample_tool"
    assert adapter.description == "A test tool."
    assert adapter.readonly is True
    assert adapter.cache is True
    assert adapter.truncate_chars == 2048
    assert adapter.pseudo is False
    schema = adapter.json_schema()
    assert isinstance(schema, dict)
    assert "query" in schema["properties"]


def test_adapter_forwards_pseudo_field() -> None:
    adapter = to_runnable(sample_pseudo)
    assert adapter.pseudo is True
    assert adapter.readonly is True


async def test_adapter_run_unpacks_args_into_kwargs() -> None:
    adapter = to_runnable(sample_tool)
    result = await adapter.run({"query": "apple", "top_k": 7})
    assert result == {"query": "apple", "top_k": 7}


async def test_adapter_run_passes_through_tool_exceptions() -> None:
    @tool(readonly=True)
    async def boom(x: int) -> dict:
        raise RuntimeError(f"nope: {x}")

    adapter = to_runnable(boom)
    with pytest.raises(RuntimeError, match="nope: 5"):
        await adapter.run({"x": 5})


def test_adapter_satisfies_runnable_tool_protocol() -> None:
    adapter = to_runnable(sample_tool)
    assert isinstance(adapter, RunnableTool)


def test_adapter_is_frozen() -> None:
    adapter = to_runnable(sample_tool)
    with pytest.raises(AttributeError):
        adapter.spec = None  # type: ignore[misc]


def test_to_runnable_rejects_plain_function() -> None:
    async def not_a_tool(x: int) -> dict:
        return {"x": x}

    with pytest.raises(ToolDefinitionError, match="not_a_tool"):
        to_runnable(not_a_tool)  # type: ignore[arg-type]


def test_to_runnable_rejects_sync_function() -> None:
    def sync_thing(x: int) -> dict:
        return {"x": x}

    with pytest.raises(ToolDefinitionError):
        to_runnable(sync_thing)  # type: ignore[arg-type]


def test_to_runnable_rejects_object_with_bogus_marker() -> None:
    async def fake(x: int) -> dict:
        return {"x": x}

    fake.__reigner_spec__ = "not a ToolSpec"  # type: ignore[attr-defined]
    with pytest.raises(ToolDefinitionError):
        to_runnable(fake)  # type: ignore[arg-type]


def test_to_runnable_returns_adapter_instance() -> None:
    adapter = to_runnable(sample_tool)
    assert isinstance(adapter, RunnableToolAdapter)
    assert adapter.spec is sample_tool.__reigner_spec__
