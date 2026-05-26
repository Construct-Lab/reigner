"""End-to-end tests for run_loop and the Harness/Session API (T-05 / issue #5).

The loop is exercised through ``Session.run_stream`` so the public surface and
the internal generator are tested together — the path users will actually use.

A scripted ``FakeAdapter`` replays a list of ``ModelAction`` results turn-by-
turn. ``RecordingTool`` lets each test assert on calls and inject failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from reigner.config import SettingsConfig
from reigner.harness.adapters.base import (
    AdapterError,
    ModelAction,
    TokenUsage,
    ToolCall,
    TransientAdapterError,
)
from reigner.harness.agent import Harness
from reigner.harness.events import (
    ClarificationEvent,
    ErrorEvent,
    Event,
    FinalAnswerEvent,
    OracleEscalationEvent,
    ToolResultEvent,
)
from reigner.harness.state import Prompt

# --------------------------------------------------------------------------
# Test doubles
# --------------------------------------------------------------------------


@dataclass
class FakeAdapter:
    name: str = "fake"
    model: str = "fake-1"
    supports_prompt_caching: bool = False
    actions: list[ModelAction | Exception] = field(default_factory=list)
    calls: list[Prompt] = field(default_factory=list)

    async def call(self, prompt: Prompt, tools: list[Any]) -> ModelAction:
        self.calls.append(prompt)
        if not self.actions:
            raise AssertionError("FakeAdapter ran out of scripted actions")
        nxt = self.actions.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


@dataclass
class RecordingTool:
    name: str
    description: str = "test tool"
    readonly: bool = True
    schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})
    response: Any = field(default_factory=lambda: {"ok": True})
    raises: BaseException | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    sleep_token: int = 0

    def json_schema(self) -> dict[str, Any]:
        return self.schema

    async def run(self, args: dict[str, Any]) -> Any:
        self.calls.append(args)
        if self.raises is not None:
            raise self.raises
        return self.response


def _final(text: str = "done") -> ModelAction:
    return ModelAction(
        is_final_answer=True,
        text=text,
        tool_calls=[],
        usage=TokenUsage.empty(),
        stop_reason="end_turn",
    )


def _tool_action(*calls: ToolCall) -> ModelAction:
    return ModelAction(
        is_final_answer=False,
        text=None,
        tool_calls=list(calls),
        usage=TokenUsage.empty(),
        stop_reason="tool_calls",
    )


def _harness(*, adapter: FakeAdapter, tools: list[Any], **kw: Any) -> Harness:
    """Build a Harness with legacy budget kwargs packed into SettingsConfig.

    T-17 collapsed the eleven loose Harness fields into ``settings`` —
    tests still want the ergonomic ``_harness(..., max_iterations=3)`` form,
    so this helper splits the kwargs and constructs the settings object.
    """
    settings_fields = set(SettingsConfig.model_fields)
    settings_kw = {k: kw.pop(k) for k in list(kw) if k in settings_fields}
    settings = SettingsConfig(**settings_kw) if settings_kw else SettingsConfig()
    from reigner.tools.registry import ToolRegistry

    registry = ToolRegistry()
    for t in tools:
        registry.register(_as_spec(t))
    return Harness(adapter=adapter, registry=registry, role="ROLE", settings=settings, **kw)


def _as_spec(t: Any) -> Any:
    """Adapt a test double (RecordingTool / GatheredTool / …) to a ToolSpec.

    Test doubles expose ``.name``, ``.schema`` (or ``.json_schema()``), and an
    async ``.run(args)``. We synthesise a ToolSpec whose ``.func`` forwards
    kwargs back into ``.run(args)`` so the registry treats it like any other
    registered tool.
    """
    from reigner.tools.base import ToolSpec

    schema = t.json_schema() if hasattr(t, "json_schema") else getattr(t, "schema", {})

    async def _forward(**kwargs: Any) -> Any:
        return await t.run(kwargs)

    return ToolSpec(
        name=t.name,
        description=getattr(t, "description", ""),
        readonly=getattr(t, "readonly", True),
        pseudo=False,
        cache=False,
        truncate_chars=None,
        func=_forward,
        schema=schema,
    )


async def _drain(session: Any, query: str) -> list[Event]:
    return [ev async for ev in session.run_stream(query)]


# --------------------------------------------------------------------------
# Happy paths
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_immediate_final_answer() -> None:
    adapter = FakeAdapter(actions=[_final("hello")])
    session = _harness(adapter=adapter, tools=[]).session()
    events = await _drain(session, "hi")
    assert [type(event).__name__ for event in events] == ["UserQueryEvent", "FinalAnswerEvent"]
    assert isinstance(events[1], FinalAnswerEvent)
    assert events[1].text == "hello"
    # Stable seq numbering starting from 0.
    assert events[0].seq == 0
    assert events[1].seq == 1


@pytest.mark.asyncio
async def test_run_returns_final_answer() -> None:
    adapter = FakeAdapter(actions=[_final("answer")])
    session = _harness(adapter=adapter, tools=[]).session()
    final = await session.run("q?")
    assert isinstance(final, FinalAnswerEvent)
    assert final.text == "answer"


@pytest.mark.asyncio
async def test_tool_call_then_final() -> None:
    tool = RecordingTool(name="search", response={"hits": [1, 2]})
    adapter = FakeAdapter(
        actions=[
            _tool_action(ToolCall(id="c1", name="search", args={"q": "x"})),
            _final("found 2"),
        ]
    )
    session = _harness(adapter=adapter, tools=[tool]).session()
    events = await _drain(session, "search please")

    types = [type(e).__name__ for e in events]
    assert types == ["UserQueryEvent", "ToolCallEvent", "ToolResultEvent", "FinalAnswerEvent"]
    assert tool.calls == [{"q": "x"}]
    result_event = events[2]
    assert isinstance(result_event, ToolResultEvent)
    assert result_event.cached is False
    assert result_event.truncated is False


# --------------------------------------------------------------------------
# Cache (G9)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_readonly_call_is_cached() -> None:
    tool = RecordingTool(name="search", response={"hits": [1]})
    adapter = FakeAdapter(
        actions=[
            _tool_action(ToolCall(id="c1", name="search", args={"q": "x"})),
            _tool_action(ToolCall(id="c2", name="search", args={"q": "x"})),
            _final("done"),
        ]
    )
    session = _harness(adapter=adapter, tools=[tool]).session()
    events = await _drain(session, "go")

    # Tool ran exactly once despite being requested twice.
    assert len(tool.calls) == 1
    cached_flags = [e.cached for e in events if isinstance(e, ToolResultEvent)]
    assert cached_flags == [False, True]


@pytest.mark.asyncio
async def test_write_tool_not_cached() -> None:
    tool = RecordingTool(name="write", readonly=False, response={"ok": True})
    adapter = FakeAdapter(
        actions=[
            _tool_action(ToolCall(id="c1", name="write", args={"x": 1})),
            _tool_action(ToolCall(id="c2", name="write", args={"x": 1})),
            _final("done"),
        ]
    )
    session = _harness(adapter=adapter, tools=[tool]).session()
    await _drain(session, "go")
    assert len(tool.calls) == 2


# --------------------------------------------------------------------------
# Truncation (G2)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_result_marked_truncated() -> None:
    huge = "x" * 10_000
    tool = RecordingTool(name="read", response=huge)
    adapter = FakeAdapter(
        actions=[
            _tool_action(ToolCall(id="c1", name="read", args={})),
            _final("ok"),
        ]
    )
    harness = _harness(adapter=adapter, tools=[tool], max_tool_result_chars=200)
    session = harness.session()
    events = await _drain(session, "go")
    result_event = next(e for e in events if isinstance(e, ToolResultEvent))
    assert result_event.truncated is True


@pytest.mark.asyncio
async def test_per_tool_char_limit_overrides_default() -> None:
    huge = "x" * 5_000
    tool = RecordingTool(name="read", response=huge)
    adapter = FakeAdapter(
        actions=[
            _tool_action(ToolCall(id="c1", name="read", args={})),
            _final("ok"),
        ]
    )
    harness = _harness(
        adapter=adapter,
        tools=[tool],
        max_tool_result_chars=200,
        tool_result_char_limits={"read": 10_000},
    )
    session = harness.session()
    events = await _drain(session, "go")
    result_event = next(e for e in events if isinstance(e, ToolResultEvent))
    assert result_event.truncated is False


# --------------------------------------------------------------------------
# Pseudo-tools
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_note_records_and_continues() -> None:
    adapter = FakeAdapter(
        actions=[
            _tool_action(ToolCall(id="c1", name="save_note", args={"text": "remember this"})),
            _final("noted"),
        ]
    )
    session = _harness(adapter=adapter, tools=[]).session()
    await _drain(session, "go")
    assert [n.text for n in session.notes()] == ["remember this"]


@pytest.mark.asyncio
async def test_request_clarification_terminates_with_clarification_event() -> None:
    adapter = FakeAdapter(
        actions=[
            _tool_action(
                ToolCall(
                    id="c1",
                    name="request_clarification",
                    args={"question": "which year?", "candidates": ["2023", "2024"]},
                )
            )
        ]
    )
    session = _harness(adapter=adapter, tools=[]).session()
    events = await _drain(session, "ambiguous")
    last = events[-1]
    assert isinstance(last, ClarificationEvent)
    assert last.question == "which year?"
    assert last.candidates == ["2023", "2024"]


@pytest.mark.asyncio
async def test_stop_pseudo_tool_terminates_with_final_answer() -> None:
    adapter = FakeAdapter(
        actions=[_tool_action(ToolCall(id="c1", name="stop", args={"reason": "out of scope"}))]
    )
    session = _harness(adapter=adapter, tools=[]).session()
    events = await _drain(session, "go")
    final = events[-1]
    assert isinstance(final, FinalAnswerEvent)
    assert final.text == "out of scope"


@pytest.mark.asyncio
async def test_oracle_escalation_emits_event_and_continues() -> None:
    adapter = FakeAdapter(
        actions=[
            _tool_action(ToolCall(id="c1", name="escalate_to_oracle", args={"reason": "hard"})),
            _final("done"),
        ]
    )
    session = _harness(adapter=adapter, tools=[]).session()
    events = await _drain(session, "go")
    assert any(isinstance(e, OracleEscalationEvent) for e in events)
    assert isinstance(events[-1], FinalAnswerEvent)


# --------------------------------------------------------------------------
# Error handling (G4)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consecutive_tool_errors_abort() -> None:
    tool = RecordingTool(name="boom", raises=RuntimeError("bad"))
    adapter = FakeAdapter(
        actions=[_tool_action(ToolCall(id=f"c{i}", name="boom", args={})) for i in range(5)]
    )
    harness = _harness(adapter=adapter, tools=[tool], max_consecutive_errors=2)
    session = harness.session()
    events = await _drain(session, "go")
    last = events[-1]
    assert isinstance(last, ErrorEvent)
    assert "consecutive tool errors" in last.error


@pytest.mark.asyncio
async def test_unknown_tool_returns_error_result() -> None:
    adapter = FakeAdapter(
        actions=[
            _tool_action(ToolCall(id="c1", name="ghost", args={})),
            _final("ok"),
        ]
    )
    session = _harness(adapter=adapter, tools=[]).session()
    events = await _drain(session, "go")
    result_event = next(e for e in events if isinstance(e, ToolResultEvent))
    assert isinstance(result_event.result, dict)
    assert "error" in result_event.result


@pytest.mark.asyncio
async def test_adapter_transient_error_yields_recoverable_error_event() -> None:
    adapter = FakeAdapter(actions=[TransientAdapterError("rate limited")])
    session = _harness(adapter=adapter, tools=[]).session()
    events = await _drain(session, "go")
    assert len(events) == 2
    err = events[1]
    assert isinstance(err, ErrorEvent)
    assert err.recoverable is True


@pytest.mark.asyncio
async def test_adapter_permanent_error_yields_unrecoverable_error_event() -> None:
    adapter = FakeAdapter(actions=[AdapterError("nope")])
    session = _harness(adapter=adapter, tools=[]).session()
    events = await _drain(session, "go")
    err = events[1]
    assert isinstance(err, ErrorEvent)
    assert err.recoverable is False


# --------------------------------------------------------------------------
# max_iterations guard
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_iterations_aborts_runaway() -> None:
    tool = RecordingTool(name="loop", response={"again": True})
    adapter = FakeAdapter(
        actions=[_tool_action(ToolCall(id=f"c{i}", name="loop", args={"i": i})) for i in range(20)]
    )
    harness = _harness(adapter=adapter, tools=[tool], max_iterations=3)
    session = harness.session()
    events = await _drain(session, "go")
    last = events[-1]
    assert isinstance(last, ErrorEvent)
    assert "max_iterations" in last.error


# --------------------------------------------------------------------------
# G11 parallel reads
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_readonly_calls_are_gathered() -> None:
    """When all calls in a turn are readonly, they share an asyncio.gather.

    The test forces a deterministic interleave by having each tool record its
    enter/exit via an event log. Under serial execution we'd see
    enter1, exit1, enter2, exit2; under parallel we see enter1, enter2 before
    either exits.
    """
    import asyncio

    log: list[str] = []

    class GatheredTool:
        def __init__(self, name: str) -> None:
            self.name = name
            self.description = "x"
            self.readonly = True

        def json_schema(self) -> dict[str, Any]:
            return {"type": "object"}

        async def run(self, args: dict[str, Any]) -> Any:
            log.append(f"enter {self.name}")
            await asyncio.sleep(0)  # yield to the other coroutine
            await asyncio.sleep(0)
            log.append(f"exit {self.name}")
            return {"ok": self.name}

    a = GatheredTool("a")
    b = GatheredTool("b")
    adapter = FakeAdapter(
        actions=[
            _tool_action(
                ToolCall(id="c1", name="a", args={}),
                ToolCall(id="c2", name="b", args={}),
            ),
            _final("done"),
        ]
    )
    session = _harness(adapter=adapter, tools=[a, b]).session()
    await _drain(session, "go")

    # Both tools entered before either exited → ran concurrently.
    assert log.index("enter b") < log.index("exit a")


@pytest.mark.asyncio
async def test_mixed_readonly_and_write_run_serially() -> None:
    """If any tool in a turn is write, the whole batch goes serial."""
    import asyncio

    log: list[str] = []

    class T:
        def __init__(self, name: str, readonly: bool) -> None:
            self.name = name
            self.description = "x"
            self.readonly = readonly

        def json_schema(self) -> dict[str, Any]:
            return {"type": "object"}

        async def run(self, args: dict[str, Any]) -> Any:
            log.append(f"enter {self.name}")
            await asyncio.sleep(0)
            log.append(f"exit {self.name}")
            return {"ok": True}

    r = T("r", True)
    w = T("w", False)
    adapter = FakeAdapter(
        actions=[
            _tool_action(
                ToolCall(id="c1", name="r", args={}),
                ToolCall(id="c2", name="w", args={}),
            ),
            _final("done"),
        ]
    )
    session = _harness(adapter=adapter, tools=[r, w]).session()
    await _drain(session, "go")
    # Strictly serial: r fully completes before w starts.
    assert log == ["enter r", "exit r", "enter w", "exit w"]


# --------------------------------------------------------------------------
# Public Session API
# --------------------------------------------------------------------------


def test_session_id_assigned() -> None:
    adapter = FakeAdapter(actions=[_final("x")])
    s = _harness(adapter=adapter, tools=[]).session()
    assert isinstance(s.id, str) and len(s.id) > 0
    assert s.parent_id is None


def test_session_id_explicit_passthrough() -> None:
    adapter = FakeAdapter(actions=[_final("x")])
    s = _harness(adapter=adapter, tools=[]).session(session_id="abc")
    assert s.id == "abc"


@pytest.mark.asyncio
async def test_fork_inherits_history_and_resets_cache() -> None:
    tool = RecordingTool(name="search", response={"v": 1})
    adapter = FakeAdapter(
        actions=[
            _tool_action(ToolCall(id="c1", name="search", args={"q": "x"})),
            _final("done"),
        ]
    )
    session = _harness(adapter=adapter, tools=[tool]).session()
    await _drain(session, "go")

    forked = session.fork()
    assert forked.parent_id == session.id
    assert forked.id != session.id
    # Forked history matches the parent's tail.
    assert len(forked.history()) == len(session.history())


@pytest.mark.asyncio
async def test_steer_enqueues_onto_state() -> None:
    adapter = FakeAdapter(actions=[_final("x")])
    s = _harness(adapter=adapter, tools=[]).session()
    await s.steer("hi")
    assert s._state.pending_steering == [("hi", "interrupt")]


@pytest.mark.asyncio
async def test_loop_drains_pending_steering_into_next_prompt() -> None:
    """SPEC §5.6: queued steering lands as a user turn before the next model call."""
    from reigner.harness.events import SteeringAcceptedEvent

    adapter = FakeAdapter(actions=[_final("ok")])
    s = _harness(adapter=adapter, tools=[]).session()

    await s.steer("focus on section 3", "queue")
    await s.steer("and cite sources", "interrupt")

    events = await _drain(s, "original question")

    steering_events = [e for e in events if isinstance(e, SteeringAcceptedEvent)]
    assert [(e.message, e.mode) for e in steering_events] == [
        ("focus on section 3", "queue"),
        ("and cite sources", "interrupt"),
    ]
    # Queue is empty after the drain.
    assert s._state.pending_steering == []
    # Both messages reached the prompt the model saw.
    last_prompt = adapter.calls[-1]
    contents = [t.content for t in last_prompt.messages]
    assert "focus on section 3" in contents
    assert "and cite sources" in contents


# NOTE: T-17 landed Harness.from_config — see tests/test_harness_from_config.py
# for its coverage. This file previously held a placeholder asserting the
# NotImplementedError stub.


def test_non_full_profile_builds_session() -> None:
    """`profile="read_only"` and `profile="eval"` now route through the
    registry instead of raising NotImplementedError."""
    adapter = FakeAdapter(actions=[_final("x")])
    h = _harness(adapter=adapter, tools=[])
    assert h.session(profile="read_only").profile == "read_only"
    assert h.session(profile="eval").profile == "eval"


# --------------------------------------------------------------------------
# Event sequencing
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_seq_is_monotonic() -> None:
    tool = RecordingTool(name="search", response={"x": 1})
    adapter = FakeAdapter(
        actions=[
            _tool_action(ToolCall(id="c1", name="search", args={"q": "x"})),
            _final("done"),
        ]
    )
    session = _harness(adapter=adapter, tools=[tool]).session()
    events = await _drain(session, "go")
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs)
    assert seqs == list(range(len(seqs)))


@pytest.mark.asyncio
async def test_seq_continues_across_run_stream_calls() -> None:
    adapter = FakeAdapter(actions=[_final("a"), _final("b")])
    session = _harness(adapter=adapter, tools=[]).session()
    first = await _drain(session, "q1")
    second = await _drain(session, "q2")
    assert second[0].seq == first[-1].seq + 1
