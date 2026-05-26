"""Plugin hooks wired into run_loop, exercised through Session.run_stream (SPEC §12).

Reuses the scripted ``FakeAdapter`` / ``RecordingTool`` doubles from
``test_loop``. Confirms transform hooks can rewrite what flows through the loop,
observe hooks fire at their event sites, and a transform-hook failure aborts the
run with an ``ErrorEvent`` (fail-loud) while an observe-hook failure does not.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from reigner.harness.adapters.base import AdapterError, ToolCall
from reigner.harness.events import ErrorEvent, FinalAnswerEvent, ToolResultEvent
from reigner.plugins.base import Plugin
from reigner.plugins.host import PluginHost
from tests.harness.test_loop import (
    FakeAdapter,
    RecordingTool,
    _drain,
    _final,
    _harness,
    _tool_action,
)


class RecordingPlugin(Plugin):
    name = "rec"

    def __init__(self) -> None:
        self.before: list[str] = []
        self.after: list[Any] = []
        self.final: list[str] = []
        self.compaction: list[int] = []
        self.errors: list[str] = []
        self.steering: list[str] = []
        self.oracle: list[str] = []

    async def before_tool_call(self, call: ToolCall, state: Any) -> ToolCall:
        self.before.append(call.name)
        return call

    async def after_tool_call(
        self, call: ToolCall, result: ToolResultEvent, state: Any
    ) -> ToolResultEvent:
        self.after.append(result.result)
        return result

    async def on_final_answer(self, answer: FinalAnswerEvent, state: Any) -> FinalAnswerEvent:
        self.final.append(answer.text)
        return answer

    async def on_compaction(self, state: Any, level: int) -> None:
        self.compaction.append(level)

    async def on_error(self, error: ErrorEvent, state: Any) -> None:
        self.errors.append(error.error)

    async def on_steering(self, event: Any, state: Any) -> None:
        self.steering.append(event.message)

    async def on_oracle_escalation(self, event: Any, state: Any) -> None:
        self.oracle.append(event.reason)


# --------------------------------------------------------------------------
# Transform hooks see and can rewrite the data flow
# --------------------------------------------------------------------------


async def test_before_and_after_fire_for_real_tool() -> None:
    rec = RecordingPlugin()
    tool = RecordingTool(name="search", response={"hits": [1]})
    adapter = FakeAdapter(
        actions=[
            _tool_action(ToolCall(id="c1", name="search", args={"q": "x"})),
            _final("done"),
        ]
    )
    session = _harness(adapter=adapter, tools=[tool], plugins=PluginHost([rec])).session()
    await _drain(session, "go")

    assert rec.before == ["search"]
    assert rec.after == [{"hits": [1]}]
    assert rec.final == ["done"]


async def test_before_tool_call_can_rewrite_args() -> None:
    class Injector(Plugin):
        name = "inject"

        async def before_tool_call(self, call: ToolCall, state: Any) -> ToolCall:
            return ToolCall(id=call.id, name=call.name, args={**call.args, "injected": True})

    tool = RecordingTool(name="search")
    adapter = FakeAdapter(
        actions=[
            _tool_action(ToolCall(id="c1", name="search", args={"q": "x"})),
            _final("done"),
        ]
    )
    session = _harness(adapter=adapter, tools=[tool], plugins=PluginHost([Injector()])).session()
    await _drain(session, "go")

    assert tool.calls == [{"q": "x", "injected": True}]


async def test_after_tool_call_rewrite_reaches_event_and_history() -> None:
    class Redactor(Plugin):
        name = "redact"

        async def after_tool_call(
            self, call: ToolCall, result: ToolResultEvent, state: Any
        ) -> ToolResultEvent:
            return dataclasses.replace(result, result={"redacted": True})

    tool = RecordingTool(name="search", response={"secret": "ssn"})
    adapter = FakeAdapter(
        actions=[
            _tool_action(ToolCall(id="c1", name="search", args={})),
            _final("done"),
        ]
    )
    session = _harness(adapter=adapter, tools=[tool], plugins=PluginHost([Redactor()])).session()
    events = await _drain(session, "go")

    result_events = [e for e in events if isinstance(e, ToolResultEvent)]
    assert result_events[0].result == {"redacted": True}
    # The post-hook payload — not the raw secret — is what lands in history.
    tool_turns = [t for t in session.history() if t.role == "tool"]
    assert "redacted" in tool_turns[0].content
    assert "ssn" not in tool_turns[0].content


async def test_on_final_answer_can_rewrite_text() -> None:
    class Shout(Plugin):
        name = "shout"

        async def on_final_answer(self, answer: FinalAnswerEvent, state: Any) -> FinalAnswerEvent:
            return dataclasses.replace(answer, text=answer.text.upper())

    adapter = FakeAdapter(actions=[_final("hi there")])
    session = _harness(adapter=adapter, tools=[], plugins=PluginHost([Shout()])).session()
    final = await session.run("q")

    assert isinstance(final, FinalAnswerEvent)
    assert final.text == "HI THERE"
    assert session.history()[-1].content == "HI THERE"


# --------------------------------------------------------------------------
# Observe hooks fire at their event sites
# --------------------------------------------------------------------------


async def test_on_steering_fires() -> None:
    rec = RecordingPlugin()
    adapter = FakeAdapter(actions=[_final("done")])
    session = _harness(adapter=adapter, tools=[], plugins=PluginHost([rec])).session()
    await session.steer("look here", "queue")
    await _drain(session, "go")

    assert rec.steering == ["look here"]


async def test_on_oracle_escalation_fires() -> None:
    rec = RecordingPlugin()
    oracle = FakeAdapter(name="oracle", model="o-1", actions=[_final("escalated answer")])
    escalate = ToolCall(id="c1", name="escalate_to_oracle", args={"reason": "hard"})
    adapter = FakeAdapter(actions=[_tool_action(escalate)])
    session = _harness(
        adapter=adapter, tools=[], oracle_adapter=oracle, plugins=PluginHost([rec])
    ).session()
    await _drain(session, "go")

    assert rec.oracle == ["hard"]
    assert rec.final == ["escalated answer"]


async def test_on_error_fires_on_adapter_failure() -> None:
    rec = RecordingPlugin()
    adapter = FakeAdapter(actions=[AdapterError("provider down")])
    session = _harness(adapter=adapter, tools=[], plugins=PluginHost([rec])).session()
    events = await _drain(session, "go")

    assert isinstance(events[-1], ErrorEvent)
    assert rec.errors and "provider down" in rec.errors[0]


# --------------------------------------------------------------------------
# Failure policy
# --------------------------------------------------------------------------


async def test_transform_failure_aborts_with_error_event() -> None:
    class BadBefore(Plugin):
        name = "bad"

        async def before_tool_call(self, call: ToolCall, state: Any) -> ToolCall:
            raise ValueError("boom")

    tool = RecordingTool(name="search")
    adapter = FakeAdapter(
        actions=[
            _tool_action(ToolCall(id="c1", name="search", args={})),
            _final("unreached"),
        ]
    )
    session = _harness(adapter=adapter, tools=[tool], plugins=PluginHost([BadBefore()])).session()
    events = await _drain(session, "go")

    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].recoverable is False
    assert "plugin 'bad'" in events[-1].error
    assert tool.calls == []  # the tool never ran — fail-loud short-circuits


async def test_observe_failure_does_not_crash_run() -> None:
    class BadOnError(Plugin):
        name = "bad-observer"

        async def on_error(self, error: ErrorEvent, state: Any) -> None:
            raise RuntimeError("observer exploded")

    adapter = FakeAdapter(actions=[AdapterError("provider down")])
    session = _harness(adapter=adapter, tools=[], plugins=PluginHost([BadOnError()])).session()
    events = await _drain(session, "go")

    # The observe-hook exception is swallowed; the error still surfaces.
    assert isinstance(events[-1], ErrorEvent)


async def test_no_plugins_is_a_clean_noop() -> None:
    tool = RecordingTool(name="search", response={"ok": 1})
    adapter = FakeAdapter(
        actions=[
            _tool_action(ToolCall(id="c1", name="search", args={})),
            _final("done"),
        ]
    )
    session = _harness(adapter=adapter, tools=[tool]).session()
    events = await _drain(session, "go")

    assert [type(e).__name__ for e in events] == [
        "UserQueryEvent",
        "ToolCallEvent",
        "ToolResultEvent",
        "FinalAnswerEvent",
    ]
