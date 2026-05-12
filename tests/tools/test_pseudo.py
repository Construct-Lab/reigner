"""Tests for the four bundled pseudo-tools.

Pseudo-tools exist to give the model verbs for managing its own loop. Their
function bodies are stubs because the loop (T-05) intercepts before
invocation; what T-08 ships is the surface (name, signature, JSON Schema,
docstring) plus registry integration.
"""

from __future__ import annotations

import pytest

from reigner.tools.base import ToolSpec
from reigner.tools.pseudo import (
    PSEUDO_TOOL_NAMES,
    escalate_to_oracle,
    request_clarification,
    save_note,
    stop,
)
from reigner.tools.registry import ToolRegistry

ALL_PSEUDO = (save_note, request_clarification, escalate_to_oracle, stop)


# ---------------------------------------------------------------------------
# Each pseudo-tool is correctly decorated
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fn", ALL_PSEUDO)
def test_pseudo_tool_decorated_correctly(fn: object) -> None:
    spec = fn.__reigner_spec__  # type: ignore[attr-defined]
    assert isinstance(spec, ToolSpec)
    assert spec.pseudo is True
    assert spec.readonly is True
    assert spec.cache is False


@pytest.mark.parametrize("fn", ALL_PSEUDO)
def test_pseudo_tool_has_substantial_docstring(fn: object) -> None:
    """Docstrings are what the model reads to decide when to call each tool.
    Guard against accidentally shipping one without a meaningful docstring.
    """
    spec = fn.__reigner_spec__  # type: ignore[attr-defined]
    assert len(spec.description) > 100, "docstring should explain when to use the tool"


def test_pseudo_tool_names_set_matches_exports() -> None:
    exported = {fn.__reigner_spec__.name for fn in ALL_PSEUDO}  # type: ignore[attr-defined]
    assert exported == PSEUDO_TOOL_NAMES


# ---------------------------------------------------------------------------
# JSON Schemas match the spec signatures (SPEC §6.4)
# ---------------------------------------------------------------------------


def test_save_note_schema() -> None:
    schema = save_note.__reigner_spec__.json_schema()
    assert schema["properties"]["text"]["type"] == "string"
    assert schema["required"] == ["text"]


def test_request_clarification_schema() -> None:
    schema = request_clarification.__reigner_spec__.json_schema()
    props = schema["properties"]
    assert props["question"]["type"] == "string"
    assert props["candidates"]["type"] == "array"
    assert props["candidates"]["items"]["type"] == "string"
    assert set(schema["required"]) == {"question", "candidates"}


def test_escalate_to_oracle_schema() -> None:
    schema = escalate_to_oracle.__reigner_spec__.json_schema()
    assert schema["properties"]["reason"]["type"] == "string"
    assert schema["required"] == ["reason"]


def test_stop_schema() -> None:
    schema = stop.__reigner_spec__.json_schema()
    assert schema["properties"]["reason"]["type"] == "string"
    assert schema["required"] == ["reason"]


# ---------------------------------------------------------------------------
# Direct invocation is unsupported and fails loudly
# ---------------------------------------------------------------------------


async def test_save_note_direct_call_raises() -> None:
    with pytest.raises(NotImplementedError, match="intercepted by the loop"):
        await save_note(text="hi")


async def test_request_clarification_direct_call_raises() -> None:
    with pytest.raises(NotImplementedError, match="intercepted by the loop"):
        await request_clarification(question="?", candidates=[])


async def test_escalate_to_oracle_direct_call_raises() -> None:
    with pytest.raises(NotImplementedError, match="intercepted by the loop"):
        await escalate_to_oracle(reason="stuck")


async def test_stop_direct_call_raises() -> None:
    with pytest.raises(NotImplementedError, match="intercepted by the loop"):
        await stop(reason="done")


# ---------------------------------------------------------------------------
# Registry integration: profile filtering (SPEC §6.3)
# ---------------------------------------------------------------------------


def _registry_with_all_pseudo() -> ToolRegistry:
    reg = ToolRegistry()
    for fn in ALL_PSEUDO:
        reg.register(fn)
    return reg


def test_pseudo_tools_register_cleanly() -> None:
    reg = _registry_with_all_pseudo()
    assert len(reg) == 4
    for name in PSEUDO_TOOL_NAMES:
        assert name in reg


def test_all_pseudo_tools_appear_in_read_only_profile() -> None:
    reg = _registry_with_all_pseudo()
    names = {s.name for s in reg.for_profile("read_only")}
    assert names == PSEUDO_TOOL_NAMES


def test_eval_profile_excludes_oracle_and_clarification() -> None:
    reg = _registry_with_all_pseudo()
    names = {s.name for s in reg.for_profile("eval")}
    assert names == {"save_note", "stop"}


# ---------------------------------------------------------------------------
# Canonical PSEUDO_TOOL_NAMES is shared with the loop's dispatch
# ---------------------------------------------------------------------------


def test_loop_uses_same_pseudo_name_set() -> None:
    """The loop's dispatch must key off the same name set that the pseudo-tools
    package exports. If these drift, the loop will silently route a pseudo-tool
    call to an external adapter."""
    from reigner.harness.loop import PSEUDO_TOOL_NAMES as loop_names

    assert loop_names is PSEUDO_TOOL_NAMES
