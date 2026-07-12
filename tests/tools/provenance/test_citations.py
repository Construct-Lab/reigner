"""Unit tests for the provenance module.

Covers the standalone surface — pseudo-tool shape, locator canonicalization,
citation id, dedup on AgentState, and the Python read accessor. Loop
integration (CitationEvent emission, lineage capture) lives in
``tests/harness/test_loop_citations.py``.
"""

from __future__ import annotations

import pytest

from reigner.harness.state import AgentState
from reigner.tools.base import ToolSpec
from reigner.tools.provenance import (
    PROVENANCE_TOOL_NAMES,
    Citation,
    canonicalize_locator,
    citation_id,
    get_citations,
    register_citation,
)

# ---------------------------------------------------------------------------
# register_citation pseudo-tool shape
# ---------------------------------------------------------------------------


def test_register_citation_is_pseudo_readonly() -> None:
    spec = register_citation.__reigner_spec__
    assert isinstance(spec, ToolSpec)
    assert spec.pseudo is True
    assert spec.readonly is True
    assert spec.cache is False
    assert spec.name == "register_citation"


def test_register_citation_schema_matches_signature() -> None:
    schema = register_citation.__reigner_spec__.json_schema()
    props = schema["properties"]
    assert props["source"]["type"] == "string"
    # locator and value are open shapes — Pydantic encodes them without a `type`
    # constraint; what matters is that all three are required.
    assert set(schema["required"]) == {"source", "locator", "value"}


def test_register_citation_has_substantial_docstring() -> None:
    spec = register_citation.__reigner_spec__
    assert len(spec.description) > 100


async def test_register_citation_direct_call_raises() -> None:
    with pytest.raises(NotImplementedError, match="intercepted by the loop"):
        await register_citation(source="x", locator={}, value=1)


def test_provenance_tool_names_set() -> None:
    assert frozenset({"register_citation"}) == PROVENANCE_TOOL_NAMES


def test_loop_unions_pseudo_and_provenance() -> None:
    """The loop must dispatch on the union, otherwise register_citation gets
    routed to an external adapter as if it were a real tool."""
    from reigner.harness.loop import (
        INTERCEPTED_TOOL_NAMES,
        PSEUDO_TOOL_NAMES,
    )

    assert "register_citation" in INTERCEPTED_TOOL_NAMES
    assert PSEUDO_TOOL_NAMES <= INTERCEPTED_TOOL_NAMES
    assert PROVENANCE_TOOL_NAMES <= INTERCEPTED_TOOL_NAMES


# ---------------------------------------------------------------------------
# canonicalize_locator
# ---------------------------------------------------------------------------


def test_canonicalize_empty_dict() -> None:
    assert canonicalize_locator({}) == ""


def test_canonicalize_flat_string_value() -> None:
    assert canonicalize_locator({"field": "rd_expense"}) == "field=rd_expense"


def test_canonicalize_sorts_keys_lexicographically() -> None:
    out = canonicalize_locator({"z": 1, "a": "x", "m": True})
    assert out == "a=x&m=True&z=1"


def test_canonicalize_two_logically_equal_dicts_match() -> None:
    a = canonicalize_locator({"a": 1, "b": 2})
    b = canonicalize_locator({"b": 2, "a": 1})
    assert a == b


def test_canonicalize_nested_value_uses_sorted_json() -> None:
    out = canonicalize_locator({"range": {"end": 10, "start": 5}})
    # Sorted-keys JSON serialization ensures stability.
    assert out == 'range={"end":10,"start":5}'


def test_canonicalize_handles_none_value() -> None:
    assert canonicalize_locator({"field": None}) == "field=None"


# ---------------------------------------------------------------------------
# citation_id
# ---------------------------------------------------------------------------


def test_citation_id_empty_locator_returns_bare_source() -> None:
    assert citation_id("AAPL/2024/metadata.json", {}) == "AAPL/2024/metadata.json"


def test_citation_id_with_locator_appends_canonical_form() -> None:
    cid = citation_id("AAPL/2024/metrics.json", {"field": "research_and_development"})
    assert cid == "AAPL/2024/metrics.json#field=research_and_development"


def test_citation_id_is_stable_across_dict_orderings() -> None:
    a = citation_id("src", {"x": 1, "y": 2})
    b = citation_id("src", {"y": 2, "x": 1})
    assert a == b


# ---------------------------------------------------------------------------
# AgentState.add_citation — dedup, no cap, returns existing on conflict
# ---------------------------------------------------------------------------


def _state() -> AgentState:
    return AgentState(session_id="t", role="ROLE")


def test_add_citation_appends() -> None:
    state = _state()
    c = Citation(
        source="AAPL/2024/metrics.json",
        locator={"field": "rd"},
        value=2_900_000_000,
        turn=0,
    )
    stored = state.add_citation(c)
    assert stored is c
    assert state.citations == [c]


def test_add_citation_dedup_returns_existing() -> None:
    state = _state()
    first = Citation(source="src", locator={"k": "v"}, value=1, turn=0)
    state.add_citation(first)
    duplicate = Citation(
        source="src",
        locator={"k": "v"},
        value=1,  # same fact re-registered on a later turn
        turn=5,
        tool_call_id="c2",
    )
    stored = state.add_citation(duplicate)
    assert stored is first
    assert len(state.citations) == 1
    # The first registration wins — replaying citations preserves the
    # historical record as originally captured.
    assert state.citations[0].turn == 0


def test_add_citation_distinct_values_at_same_locator_coexist() -> None:
    # Prose sections are one blob, so distinct facts share a locator
    # (e.g. {line: 1}). Keying dedup on value keeps every fact alive so
    # the faithfulness check can find each cited claim.
    state = _state()
    loc = {"line": 1}
    net_sales = Citation(source="AMZN/2024/sections/mdna", locator=loc, value=637_959, turn=0)
    north_america = Citation(source="AMZN/2024/sections/mdna", locator=loc, value=387_497, turn=0)
    state.add_citation(net_sales)
    stored = state.add_citation(north_america)
    assert stored is north_america
    assert [c.value for c in state.citations] == [637_959, 387_497]


def test_add_citation_dedup_uses_canonical_locator() -> None:
    state = _state()
    state.add_citation(Citation(source="s", locator={"a": 1, "b": 2}, value=10, turn=0))
    state.add_citation(Citation(source="s", locator={"b": 2, "a": 1}, value=10, turn=1))
    assert len(state.citations) == 1


def test_add_citation_no_cap() -> None:
    state = _state()
    for i in range(200):
        state.add_citation(
            Citation(source=f"src-{i}", locator={}, value=i, turn=0),
        )
    assert len(state.citations) == 200


# ---------------------------------------------------------------------------
# get_citations
# ---------------------------------------------------------------------------


def test_get_citations_returns_copy() -> None:
    state = _state()
    c = Citation(source="src", locator={}, value=1, turn=0)
    state.add_citation(c)
    out = get_citations(state)
    assert out == [c]
    out.append(Citation(source="leak", locator={}, value=0, turn=0))
    # Mutating the returned list must not affect the state.
    assert len(state.citations) == 1


def test_get_citations_empty_state() -> None:
    state = _state()
    assert get_citations(state) == []
