"""Unit tests for harness.nudges (T-06, G3/G4)."""

from __future__ import annotations

from reigner.harness.nudges import error_nudge, iteration_nudge
from reigner.harness.state import AgentState


def _state(**kw: object) -> AgentState:
    base: dict[str, object] = {
        "session_id": "s",
        "role": "r",
        "token_counter": lambda s: len(s),  # deterministic, no tiktoken
    }
    base.update(kw)
    return AgentState(**base)  # type: ignore[arg-type]


def test_iteration_nudge_skips_zero() -> None:
    s = _state()
    s.iterations = 0
    assert iteration_nudge(s) is None


def test_iteration_nudge_fires_on_interval() -> None:
    s = _state(nudge_interval=3)
    s.iterations = 3
    msg = iteration_nudge(s)
    assert msg is not None and "iterations" in msg


def test_iteration_nudge_skips_off_interval() -> None:
    s = _state(nudge_interval=3)
    s.iterations = 4
    assert iteration_nudge(s) is None


def test_iteration_nudge_disabled_by_zero_interval() -> None:
    s = _state(nudge_interval=0)
    s.iterations = 5
    assert iteration_nudge(s) is None


def test_error_nudge_below_threshold() -> None:
    s = _state(max_consecutive_errors=3)
    s.record_tool_error()
    assert error_nudge(s) is None


def test_error_nudge_fires_at_threshold() -> None:
    s = _state(max_consecutive_errors=3)
    for _ in range(3):
        s.record_tool_error()
    msg = error_nudge(s)
    assert msg is not None and "consecutive" in msg


def test_error_nudge_clears_on_success() -> None:
    s = _state(max_consecutive_errors=3)
    for _ in range(3):
        s.record_tool_error()
    s.record_tool_success()
    assert error_nudge(s) is None
    assert s.error_nudge_injected is False
