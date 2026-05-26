"""Round-trip and contract tests for the event protocol (T-02)."""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import UTC, datetime
from typing import Any

import pytest

from reigner.harness import events as ev


def _envelope(seq: int = 1) -> dict[str, Any]:
    return {"seq": seq, "session_id": "s-1", "turn": 0}


SAMPLES: list[ev.Event] = [
    ev.UserQueryEvent(**_envelope(1), query="what changed?"),
    ev.StatusEvent(**_envelope(2), message="thinking"),
    ev.ToolCallEvent(**_envelope(3), name="fs_read", args={"path": "x"}, call_id="c1"),
    ev.ToolResultEvent(
        **_envelope(4), call_id="c1", result={"ok": True, "n": 3}, truncated=False, cached=True
    ),
    ev.CitationEvent(**_envelope(5), source="art-7", locator={"line": 12}, value="42"),
    ev.ClarificationEvent(**_envelope(6), question="which year?", candidates=[2023, 2024]),
    ev.FinalAnswerEvent(**_envelope(7), text="done", metadata={"tokens": 10}),
    ev.ErrorEvent(**_envelope(8), error="boom", recoverable=True),
    ev.CompactionEvent(**_envelope(9), level=1, tokens_freed=500),
    ev.OracleEscalationEvent(**_envelope(10), reason="hard", from_model="haiku", to_model="opus"),
    ev.SteeringAcceptedEvent(**_envelope(11), message="focus on §3", mode="append"),
]


@pytest.mark.parametrize("event", SAMPLES, ids=lambda e: e.type)
def test_round_trip(event: ev.Event) -> None:
    line = ev.to_json(event)
    restored = ev.from_json(line)
    assert type(restored) is type(event)
    for f in fields(event):
        assert getattr(restored, f.name) == getattr(event, f.name), f.name


@pytest.mark.parametrize("event", SAMPLES, ids=lambda e: e.type)
def test_envelope_present(event: ev.Event) -> None:
    assert isinstance(event.seq, int)
    assert isinstance(event.session_id, str) and event.session_id
    assert isinstance(event.turn, int)
    assert isinstance(event.ts, datetime)
    assert event.ts.tzinfo is not None


def test_strict_result_rejection() -> None:
    class NotJson:
        pass

    bad = ev.ToolResultEvent(
        **_envelope(), call_id="c1", result=NotJson(), truncated=False, cached=False
    )
    with pytest.raises(TypeError, match="result"):
        ev.to_json(bad)


def test_strict_nested_result_rejection() -> None:
    bad = ev.ToolResultEvent(
        **_envelope(),
        call_id="c1",
        result={"items": [1, {"bad": object()}]},
        truncated=False,
        cached=False,
    )
    with pytest.raises(TypeError, match=r"result\.items\[1\]\.bad"):
        ev.to_json(bad)


def test_unknown_type_rejection() -> None:
    line = json.dumps({"type": "bogus", "seq": 1, "session_id": "s", "turn": 0})
    with pytest.raises(ev.UnknownEventType):
        ev.from_json(line)


def test_missing_type_rejection() -> None:
    line = json.dumps({"seq": 1, "session_id": "s", "turn": 0})
    with pytest.raises(ev.UnknownEventType):
        ev.from_json(line)


def test_registry_completeness() -> None:
    assert len(ev.EVENT_TYPES) == 11
    expected = {
        "user_query",
        "status",
        "tool_call",
        "tool_result",
        "citation",
        "clarification",
        "final_answer",
        "error",
        "compaction",
        "oracle",
        "steering",
    }
    assert set(ev.EVENT_TYPES) == expected
    for name, cls in ev.EVENT_TYPES.items():
        assert cls.type == name
        assert issubclass(cls, ev.Event)


def test_type_is_class_level() -> None:
    assert ev.UserQueryEvent.type == "user_query"
    assert ev.StatusEvent.type == "status"
    assert ev.ToolResultEvent.type == "tool_result"


def test_ts_round_trips_as_iso() -> None:
    fixed = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
    e = ev.StatusEvent(**_envelope(), message="hi", ts=fixed)
    restored = ev.from_json(ev.to_json(e))
    assert restored.ts == fixed


def test_schema_version_constant() -> None:
    assert isinstance(ev.SCHEMA_VERSION, int)
    assert ev.SCHEMA_VERSION >= 1
