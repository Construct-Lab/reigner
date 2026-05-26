"""Session reconstruction, fork, and live replay tests for T-25."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from reigner.config import SessionsConfig, SettingsConfig
from reigner.harness.adapters.base import ToolCall
from reigner.harness.agent import Harness, Session
from reigner.harness.events import FinalAnswerEvent, ToolCallEvent, ToolResultEvent, UserQueryEvent
from reigner.sessions.replay import ReplayError, reconstruct
from tests.harness.test_loop import FakeAdapter, _final, _tool_action


def _harness(tmp_path: Path, actions: list[Any]) -> Harness:
    return Harness(
        adapter=FakeAdapter(actions=actions),
        settings=SettingsConfig(),
        sessions=SessionsConfig(store_path=str(tmp_path / "sessions")),
        role="ROLE",
    )


async def _run(session: Session, query: str) -> None:
    async for _ in session.run_stream(query):
        pass


def _history_payload(session: Session) -> list[tuple[str, str, list[dict[str, Any]], str | None]]:
    return [
        (turn.role, turn.content, turn.tool_calls, turn.tool_call_id) for turn in session.history()
    ]


@pytest.mark.asyncio
async def test_load_reconstructs_history_notes_and_citations(tmp_path: Path) -> None:
    harness = _harness(
        tmp_path,
        [
            _tool_action(ToolCall(id="n1", name="save_note", args={"text": "FY24 note"})),
            _tool_action(
                ToolCall(
                    id="c1",
                    name="register_citation",
                    args={"source": "metrics.json", "locator": {"field": "rd"}, "value": 9},
                )
            ),
            _final("answer"),
        ],
    )
    original = harness.session(session_id="source")
    await _run(original, "question")

    loaded = Session.load(original.id, harness=harness)
    rebuilt = reconstruct(
        original.events(), settings=harness.settings, session_id=original.id, role=harness.role
    )

    assert _history_payload(loaded) == _history_payload(original)
    assert [(note.text, note.turn) for note in loaded.notes()] == [("FY24 note", 0)]
    assert [
        (citation.source, citation.locator, citation.value) for citation in loaded.citations()
    ] == [("metrics.json", {"field": "rd"}, 9)]
    assert [turn.content for turn in rebuilt.history] == [
        turn.content for turn in original.history()
    ]


@pytest.mark.asyncio
async def test_reconstruct_preserves_terminal_stop_tool_history(tmp_path: Path) -> None:
    harness = _harness(
        tmp_path,
        [_tool_action(ToolCall(id="s1", name="stop", args={"reason": "finished"}))],
    )
    session = harness.session(session_id="stopped")
    await _run(session, "go")

    loaded = Session.load(session.id, harness=harness)

    assert _history_payload(loaded) == _history_payload(session)
    assert loaded.history()[-1].content == "finished"


def test_reconstruct_preserves_order_for_repeated_identical_tool_arguments() -> None:
    sid = "repeat"
    events = [
        UserQueryEvent(seq=0, session_id=sid, turn=0, query="go"),
        ToolCallEvent(seq=1, session_id=sid, turn=0, name="lookup", args={"q": "x"}, call_id="a"),
        ToolResultEvent(
            seq=2,
            session_id=sid,
            turn=0,
            call_id="a",
            result={"value": 1},
            truncated=False,
            cached=False,
        ),
        ToolCallEvent(seq=3, session_id=sid, turn=1, name="lookup", args={"q": "x"}, call_id="b"),
        ToolResultEvent(
            seq=4,
            session_id=sid,
            turn=1,
            call_id="b",
            result={"value": 2},
            truncated=False,
            cached=False,
        ),
        FinalAnswerEvent(seq=5, session_id=sid, turn=2, text="done", metadata={}),
    ]

    state = reconstruct(events, settings=SettingsConfig(), session_id=sid)

    tool_contents = [turn.content for turn in state.history if turn.role == "tool"]
    assert tool_contents == ['{"value": 1}', '{"value": 2}']


def test_reconstruct_rejects_log_without_recorded_query() -> None:
    event = FinalAnswerEvent(seq=0, session_id="legacy", turn=0, text="old", metadata={})
    with pytest.raises(ReplayError, match="no UserQueryEvent"):
        reconstruct([event], settings=SettingsConfig(), session_id="legacy")


@pytest.mark.asyncio
async def test_fork_copies_complete_round_prefix_and_rewrites_session_id(tmp_path: Path) -> None:
    harness = _harness(tmp_path, [_final("one"), _final("two")])
    parent = harness.session(session_id="parent")
    await _run(parent, "q1")
    await _run(parent, "q2")

    child = parent.fork(at_turn=2)
    copied = child.events()

    assert child.parent_id == parent.id
    assert [event.type for event in copied] == ["user_query", "final_answer"]
    assert all(event.session_id == child.id for event in copied)
    assert [turn.content for turn in child.history()] == ["q1", "one"]
    assert list(harness.store.load_events(child.id)) == copied


@pytest.mark.asyncio
async def test_replay_creates_diffable_child_and_does_not_mutate_original(tmp_path: Path) -> None:
    harness = _harness(tmp_path, [_final("one"), _final("old answer"), _final("new answer")])
    parent = harness.session(session_id="parent")
    await _run(parent, "q1")
    await _run(parent, "q2")
    original_events = parent.events()

    child = await parent.replay(at_turn=2)

    assert parent.events() == original_events
    assert child.parent_id == parent.id
    assert [turn.content for turn in child.history()] == ["q1", "one", "q2", "new answer"]
    assert isinstance(child.events()[-1], FinalAnswerEvent)
    assert child.events()[-1].text == "new answer"
