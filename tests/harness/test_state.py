"""Unit tests for AgentState (T-03 / issue #3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reigner.harness.state import AgentState, Turn


@dataclass
class _FakeTool:
    name: str
    description: str
    readonly: bool
    schema: dict[str, Any]

    def json_schema(self) -> dict[str, Any]:
        return self.schema


def _make_state(**overrides: Any) -> AgentState:
    defaults: dict[str, Any] = {
        "session_id": "s1",
        "role": "You are a test agent.",
        "token_counter": len,  # cheap, deterministic
        "context_budget_tokens": 1000,
        "max_iterations": 5,
        "max_session_notes": 3,
    }
    defaults.update(overrides)
    return AgentState(**defaults)


# --------------------------------------------------------------------------
# Steering queue
# --------------------------------------------------------------------------


def test_steering_starts_empty() -> None:
    s = _make_state()
    assert s.has_pending_steering() is False
    assert s.consume_steering() == []


def test_steering_enqueue_and_drain_fifo() -> None:
    s = _make_state()
    s.enqueue_steering("first", "interrupt")
    s.enqueue_steering("second", "queue")
    assert s.has_pending_steering()
    drained = s.consume_steering()
    assert drained == [("first", "interrupt"), ("second", "queue")]
    assert s.has_pending_steering() is False


def test_consume_steering_clears_queue() -> None:
    s = _make_state()
    s.enqueue_steering("hi")
    s.consume_steering()
    s.enqueue_steering("again")
    assert s.consume_steering() == [("again", "interrupt")]


# --------------------------------------------------------------------------
# refresh_context (G6)
# --------------------------------------------------------------------------


def test_refresh_context_populates_dynamic_fields() -> None:
    s = _make_state(max_iterations=10)
    s.refresh_context()
    ctx = s.dynamic_context
    assert ctx["iters_remaining"] == 10
    assert isinstance(ctx["now"], str)
    assert isinstance(ctx["answer_id"], str) and len(ctx["answer_id"]) == 32


def test_refresh_context_decrements_iters_remaining() -> None:
    s = _make_state(max_iterations=5)
    s.iterations = 2
    s.refresh_context()
    assert s.dynamic_context["iters_remaining"] == 3


def test_refresh_context_floors_at_zero() -> None:
    s = _make_state(max_iterations=2)
    s.iterations = 99
    s.refresh_context()
    assert s.dynamic_context["iters_remaining"] == 0


def test_refresh_context_changes_answer_id_each_call() -> None:
    s = _make_state()
    s.refresh_context()
    first = s.dynamic_context["answer_id"]
    s.refresh_context()
    assert s.dynamic_context["answer_id"] != first


# --------------------------------------------------------------------------
# build_prompt (G1)
# --------------------------------------------------------------------------


def test_build_prompt_separates_stable_and_dynamic() -> None:
    tool = _FakeTool("get_x", "fetches x", True, {"type": "object"})
    s = _make_state(tools=[tool])
    s.append_turn(Turn(role="user", content="hello"))
    s.refresh_context()

    p = s.build_prompt()
    assert "test agent" in p.stable
    assert "get_x" in p.stable
    assert p.messages == s.history
    assert p.messages is not s.history  # defensive copy
    assert "iters_remaining" in p.dynamic_context


def test_stable_text_byte_identical_across_iterations() -> None:
    tool = _FakeTool("t", "d", True, {"k": 1})
    s = _make_state(tools=[tool])
    first = s.build_prompt().stable
    s.append_turn(Turn(role="user", content="anything"))
    s.iterations = 4
    s.refresh_context()
    assert s.build_prompt().stable == first


def test_dynamic_context_is_a_copy() -> None:
    s = _make_state()
    s.refresh_context()
    p = s.build_prompt()
    p.dynamic_context["mutated"] = True
    assert "mutated" not in s.dynamic_context


# --------------------------------------------------------------------------
# context_pressure
# --------------------------------------------------------------------------


def test_context_pressure_zero_when_empty() -> None:
    s = _make_state(role="", context_budget_tokens=100)
    assert s.context_pressure() == 0.0


def test_context_pressure_scales_with_history() -> None:
    s = _make_state(role="x" * 10, context_budget_tokens=100)
    low = s.context_pressure()
    s.append_turn(Turn(role="user", content="y" * 50))
    high = s.context_pressure()
    assert high > low


def test_context_pressure_can_exceed_one() -> None:
    s = _make_state(role="x" * 200, context_budget_tokens=100)
    assert s.context_pressure() > 1.0


def test_context_pressure_zero_budget_returns_zero() -> None:
    s = _make_state(role="x" * 100, context_budget_tokens=0)
    assert s.context_pressure() == 0.0


# --------------------------------------------------------------------------
# Notes (G8 scratchpad)
# --------------------------------------------------------------------------


def test_add_note_caps_at_max_with_fifo_eviction() -> None:
    s = _make_state(max_session_notes=2)
    s.add_note("a")
    s.add_note("b")
    s.add_note("c")
    assert [n.text for n in s.notes] == ["b", "c"]


def test_add_note_records_iteration() -> None:
    s = _make_state()
    s.iterations = 7
    note = s.add_note("hello")
    assert note.turn == 7


# --------------------------------------------------------------------------
# Error counter (G4 hook)
# --------------------------------------------------------------------------


def test_consecutive_errors_increments_and_resets() -> None:
    s = _make_state()
    assert s.consecutive_errors() == 0
    s.record_tool_error()
    s.record_tool_error()
    assert s.consecutive_errors() == 2
    s.record_tool_success()
    assert s.consecutive_errors() == 0


# --------------------------------------------------------------------------
# Default tiktoken counter wires up
# --------------------------------------------------------------------------


def test_default_token_counter_works() -> None:
    s = AgentState(session_id="s", role="hello world")
    # Don't assert exact count — just that the default counter runs and is >0.
    assert s.tokens_used() > 0
