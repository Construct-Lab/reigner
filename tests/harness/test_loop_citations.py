"""Loop-side tests for the register_citation pseudo-tool.

Verifies the loop intercepts ``register_citation`` rather than routing it as
a real tool, emits a CitationEvent in the event stream, appends a Citation
to AgentState with lineage fields populated, and continues looping (unlike
``stop``/``request_clarification``, register_citation does not terminate).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from reigner.config import SettingsConfig
from reigner.harness.adapters.base import (
    ModelAction,
    TokenUsage,
    ToolCall,
)
from reigner.harness.agent import Harness
from reigner.harness.events import (
    CitationEvent,
    Event,
    FinalAnswerEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from reigner.harness.state import Prompt
from reigner.tools.registry import ToolRegistry


@dataclass
class FakeAdapter:
    name: str = "fake"
    model: str = "fake-1"
    supports_prompt_caching: bool = False
    actions: list[ModelAction] = field(default_factory=list)
    calls: list[Prompt] = field(default_factory=list)

    async def call(self, prompt: Prompt, tools: list[Any]) -> ModelAction:
        self.calls.append(prompt)
        return self.actions.pop(0)


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


def _harness(adapter: FakeAdapter) -> Harness:
    return Harness(
        adapter=adapter,
        registry=ToolRegistry(),
        role="ROLE",
        settings=SettingsConfig(),
    )


async def _drain(session: Any, query: str) -> list[Event]:
    return [ev async for ev in session.run_stream(query)]


@pytest.mark.asyncio
async def test_register_citation_emits_event_and_stores_citation() -> None:
    adapter = FakeAdapter(
        actions=[
            _tool_action(
                ToolCall(
                    id="c1",
                    name="register_citation",
                    args={
                        "source": "AAPL/2024/metrics.json",
                        "locator": {"field": "research_and_development"},
                        "value": 2_900_000_000,
                    },
                )
            ),
            _final("Apple's R&D was $2.9B."),
        ]
    )
    session = _harness(adapter).session()
    events = await _drain(session, "What was Apple's R&D in 2024?")

    types = [type(e).__name__ for e in events]
    assert types == [
        "UserQueryEvent",
        "ToolCallEvent",
        "CitationEvent",
        "ToolResultEvent",
        "FinalAnswerEvent",
    ]

    cite = next(e for e in events if isinstance(e, CitationEvent))
    assert cite.source == "AAPL/2024/metrics.json"
    assert cite.locator == {"field": "research_and_development"}
    assert cite.value == 2_900_000_000

    stored = session.citations()
    assert len(stored) == 1
    assert stored[0].source == "AAPL/2024/metrics.json"
    # Lineage fields populated by the loop dispatch.
    assert stored[0].tool_call_id == "c1"
    assert stored[0].tool_name == "register_citation"
    assert stored[0].turn == 0


@pytest.mark.asyncio
async def test_register_citation_does_not_terminate_loop() -> None:
    """register_citation is a mid-loop verb — the loop must keep going so the
    model can compose its final answer after recording the citation."""
    adapter = FakeAdapter(
        actions=[
            _tool_action(
                ToolCall(
                    id="c1",
                    name="register_citation",
                    args={"source": "s", "locator": {}, "value": 1},
                )
            ),
            _final("done"),
        ]
    )
    session = _harness(adapter).session()
    events = await _drain(session, "go")
    # Two model calls => loop continued past the citation.
    assert len(adapter.calls) == 2
    assert isinstance(events[-1], FinalAnswerEvent)


@pytest.mark.asyncio
async def test_register_citation_result_includes_citation_id() -> None:
    adapter = FakeAdapter(
        actions=[
            _tool_action(
                ToolCall(
                    id="c1",
                    name="register_citation",
                    args={
                        "source": "AAPL/2024/metrics.json",
                        "locator": {"field": "rd"},
                        "value": 1,
                    },
                )
            ),
            _final("ok"),
        ]
    )
    session = _harness(adapter).session()
    events = await _drain(session, "go")
    result_ev = next(e for e in events if isinstance(e, ToolResultEvent))
    assert result_ev.result == {
        "ok": True,
        "citation_id": "AAPL/2024/metrics.json#field=rd",
    }


@pytest.mark.asyncio
async def test_duplicate_register_citation_is_deduplicated() -> None:
    """Two register_citation calls with the same (source, locator) keep one
    Citation on state — but each emits its own ToolCall/CitationEvent pair so
    the event stream remains an honest record of what the model did."""
    adapter = FakeAdapter(
        actions=[
            _tool_action(
                ToolCall(
                    id="c1",
                    name="register_citation",
                    args={"source": "s", "locator": {"k": "v"}, "value": 1},
                )
            ),
            _tool_action(
                ToolCall(
                    id="c2",
                    name="register_citation",
                    args={"source": "s", "locator": {"k": "v"}, "value": 1},
                )
            ),
            _final("done"),
        ]
    )
    session = _harness(adapter).session()
    await _drain(session, "go")
    assert len(session.citations()) == 1


@pytest.mark.asyncio
async def test_register_citation_with_non_dict_locator_is_coerced() -> None:
    """The model may emit a malformed locator (string instead of dict). The
    loop coerces rather than crashing — citations should remain reachable
    even with messy model output."""
    adapter = FakeAdapter(
        actions=[
            _tool_action(
                ToolCall(
                    id="c1",
                    name="register_citation",
                    args={"source": "s", "locator": "stringified", "value": 1},
                )
            ),
            _final("ok"),
        ]
    )
    session = _harness(adapter).session()
    events = await _drain(session, "go")
    assert any(isinstance(e, CitationEvent) for e in events)
    assert len(session.citations()) == 1
    assert session.citations()[0].locator == {"_": "stringified"}


@pytest.mark.asyncio
async def test_register_citation_not_treated_as_real_tool() -> None:
    """Smoke test: the loop's `real_calls` filter must exclude register_citation,
    otherwise it would try to dispatch via the (nonexistent) tool registry and
    fail the call as if it were an unknown tool."""
    adapter = FakeAdapter(
        actions=[
            _tool_action(
                ToolCall(
                    id="c1",
                    name="register_citation",
                    args={"source": "s", "locator": {}, "value": 1},
                )
            ),
            _final("ok"),
        ]
    )
    # tools=[] — there is no real tool that could service register_citation.
    # If interception worked, the loop must still complete normally.
    session = _harness(adapter).session()
    events = await _drain(session, "go")
    assert isinstance(events[-1], FinalAnswerEvent)


@pytest.mark.asyncio
async def test_register_citation_alongside_real_tool_call() -> None:
    """The model may emit a register_citation in the same turn as a real
    read tool. Both should be processed; emission order matches model order."""
    from tests.harness.test_loop import RecordingTool, _as_spec

    tool = RecordingTool(name="lookup", response={"v": 42})
    adapter = FakeAdapter(
        actions=[
            _tool_action(
                ToolCall(id="c1", name="lookup", args={"key": "x"}),
                ToolCall(
                    id="c2",
                    name="register_citation",
                    args={"source": "s", "locator": {"k": "x"}, "value": 42},
                ),
            ),
            _final("done"),
        ]
    )
    registry = ToolRegistry()
    registry.register(_as_spec(tool))
    harness = Harness(adapter=adapter, registry=registry, role="ROLE", settings=SettingsConfig())
    session = harness.session()
    events = await _drain(session, "go")

    # The real tool ran.
    assert tool.calls == [{"key": "x"}]
    # A citation was registered.
    assert len(session.citations()) == 1
    # CitationEvent appears in the stream.
    assert any(isinstance(e, CitationEvent) for e in events)
    # And there is a ToolCallEvent for both calls.
    assert sum(isinstance(e, ToolCallEvent) for e in events) == 2
