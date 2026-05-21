"""Tests for ToolRegistry: registration, profile filtering, schema list."""

from __future__ import annotations

import pytest

from reigner.tools.base import RunnableToolAdapter, ToolSpec, to_runnable, tool
from reigner.tools.registry import ToolRegistrationError, ToolRegistry

# ---------------------------------------------------------------------------
# Fixtures: a small zoo of decorated functions covering each category
# ---------------------------------------------------------------------------


@tool(readonly=True)
async def read_a(x: int) -> dict:
    """A read tool."""
    return {"x": x}


@tool(readonly=True)
async def read_b(y: int) -> dict:
    """Another read tool."""
    return {"y": y}


@tool(readonly=False)
async def write_a(text: str) -> dict:
    """A write tool."""
    return {"text": text}


@tool(readonly=True, pseudo=True)
async def save_note(text: str) -> dict:
    """A pseudo-tool."""
    return {"text": text}


@tool(readonly=True, pseudo=True)
async def escalate_to_oracle(reason: str) -> dict:
    """Escalate to oracle (excluded from eval)."""
    return {"reason": reason}


@tool(readonly=True, pseudo=True)
async def request_clarification(question: str) -> dict:
    """Ask the user (excluded from eval)."""
    return {"q": question}


# ---------------------------------------------------------------------------
# register: accepts decorated function or bare ToolSpec
# ---------------------------------------------------------------------------


def test_register_decorated_function() -> None:
    reg = ToolRegistry()
    spec = reg.register(read_a)
    assert isinstance(spec, ToolSpec)
    assert "read_a" in reg
    assert reg.get("read_a") is spec


def test_register_bare_spec() -> None:
    reg = ToolRegistry()
    spec = read_a.__reigner_spec__
    reg.register(spec)
    assert reg.get("read_a") is spec


def test_register_rejects_non_decorated_function() -> None:
    async def plain(x: int) -> dict:
        return {}

    reg = ToolRegistry()
    with pytest.raises(ToolRegistrationError, match="not a @tool-decorated function"):
        reg.register(plain)


def test_register_runnable_tool_adapter() -> None:
    """Adapters from ArtifactStore.tools() / Bm25Index.tools() register cleanly."""
    reg = ToolRegistry()
    adapter = to_runnable(read_a)
    spec = reg.register(adapter)
    assert isinstance(spec, ToolSpec)
    assert reg.get("read_a") is adapter.spec


def test_for_profile_returns_runnable_adapters() -> None:
    """The loop needs `.run(args)`; for_profile() yields runnables, not specs."""
    reg = _populated_registry()
    items = reg.for_profile("full")
    assert items, "expected non-empty profile output"
    assert all(isinstance(a, RunnableToolAdapter) for a in items)
    assert all(callable(a.run) for a in items)


def test_register_raises_on_name_collision() -> None:
    reg = ToolRegistry()
    reg.register(read_a)
    with pytest.raises(ToolRegistrationError, match="already registered"):
        reg.register(read_a)


# ---------------------------------------------------------------------------
# Profile filtering (SPEC §6.3)
# ---------------------------------------------------------------------------


def _populated_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for fn in (read_a, read_b, write_a, save_note, escalate_to_oracle, request_clarification):
        reg.register(fn)
    return reg


def test_profile_full_returns_everything() -> None:
    reg = _populated_registry()
    names = {s.name for s in reg.for_profile("full")}
    assert names == {
        "read_a",
        "read_b",
        "write_a",
        "save_note",
        "escalate_to_oracle",
        "request_clarification",
    }


def test_profile_read_only_excludes_write_tools() -> None:
    reg = _populated_registry()
    names = {s.name for s in reg.for_profile("read_only")}
    assert "write_a" not in names
    assert {"read_a", "read_b", "save_note", "escalate_to_oracle", "request_clarification"} <= names


def test_profile_eval_excludes_oracle_and_clarification() -> None:
    reg = _populated_registry()
    names = {s.name for s in reg.for_profile("eval")}
    assert "write_a" not in names
    assert "escalate_to_oracle" not in names
    assert "request_clarification" not in names
    assert {"read_a", "read_b", "save_note"} <= names


def test_profile_unknown_raises() -> None:
    reg = _populated_registry()
    with pytest.raises(ValueError, match="unknown profile"):
        reg.for_profile("bogus")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# schemas() and container protocols
# ---------------------------------------------------------------------------


def test_schemas_returns_one_entry_per_tool_in_order() -> None:
    reg = ToolRegistry()
    reg.register(read_a)
    reg.register(write_a)
    schemas = reg.schemas()
    assert len(schemas) == 2
    assert all(isinstance(s, dict) for s in schemas)


def test_container_protocols() -> None:
    reg = ToolRegistry()
    reg.register(read_a)
    reg.register(write_a)
    assert "read_a" in reg
    assert "missing" not in reg
    assert len(reg) == 2
    names = [s.name for s in reg]
    assert names == ["read_a", "write_a"]
