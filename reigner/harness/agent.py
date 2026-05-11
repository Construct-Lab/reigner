"""Public ``Harness`` and ``Session`` API (SPEC.md §5.1, issue #5).

``Harness`` is the immutable configured loop — model adapter, tools, role,
guardrail thresholds. ``Session`` is the mutable per-conversation container
on top: it owns ``AgentState``, the tool-result cache, and the event log.

What's intentionally stubbed in T-05:

- ``Harness.from_config`` raises until the config loader (T-26) lands.
- ``Session.steer`` raises until T-06 wires the steering machinery into the
  loop. The signature is in place so the public surface matches the issue.
- ``Session.save`` / ``Session.load`` raise until T-23 builds the JSONL
  session store.
- Profile filtering is gated on the tool registry (T-07); only ``"full"`` is
  accepted today.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

from reigner.harness.adapters.base import ModelAdapter
from reigner.harness.cache import ToolResultCache
from reigner.harness.events import Event, FinalAnswerEvent
from reigner.harness.loop import RunnableTool, run_loop
from reigner.harness.state import AgentState, Note, SteeringMode, Turn

Profile = Literal["full", "read_only", "eval"]


@dataclass(kw_only=True)
class Harness:
    """Immutable configured agent. Build once, spawn many sessions.

    The fields here are the knobs the loop reads each iteration. Defaults
    track SPEC §13. Any field not provided uses the AgentState default.
    """

    adapter: ModelAdapter
    tools: list[RunnableTool] = field(default_factory=list)
    role: str = ""
    oracle_adapter: ModelAdapter | None = None

    # Loop budgets — see SPEC §13 / state.AgentState defaults.
    max_iterations: int = 25
    context_budget_tokens: int = 100_000
    max_tool_result_chars: int = 4000
    tool_result_char_limits: dict[str, int] = field(default_factory=dict)
    nudge_interval: int = 3
    max_consecutive_errors: int = 3
    max_session_notes: int = 20
    history_keep_recent: int = 3
    compaction_thresholds: tuple[float, float, float] = (0.80, 0.90, 0.95)

    @classmethod
    def from_config(cls, path: str, tools: list[RunnableTool] | None = None) -> Harness:
        raise NotImplementedError(
            "Harness.from_config requires the reigner.yaml loader (later task)"
        )

    def session(
        self,
        *,
        state: dict[str, object] | None = None,
        history: list[Turn] | None = None,
        session_id: str | None = None,
        profile: Profile = "full",
    ) -> Session:
        if profile != "full":
            # Profile filtering depends on tool metadata that lands with T-07.
            raise NotImplementedError(
                f"profile {profile!r} requires the tool registry (T-07); "
                "only 'full' is supported today"
            )
        # `state` is reserved for user-attached metadata (e.g. {"user_id": "u1"}
        # per SPEC §4); persisted alongside the session by T-23.
        _ = state
        return Session(
            harness=self,
            session_id=session_id or uuid.uuid4().hex,
            parent_id=None,
            initial_history=list(history or []),
        )


class Session:
    """One conversation. Mutable. Forkable. Drives ``run_loop`` per query."""

    def __init__(
        self,
        *,
        harness: Harness,
        session_id: str,
        parent_id: str | None,
        initial_history: list[Turn],
    ) -> None:
        self.harness = harness
        self.id = session_id
        self.parent_id = parent_id
        self._cache = ToolResultCache()
        self._state = AgentState(
            session_id=session_id,
            role=harness.role,
            tools=list(harness.tools),
            adapter=harness.adapter,
            oracle_adapter=harness.oracle_adapter,
            max_iterations=harness.max_iterations,
            context_budget_tokens=harness.context_budget_tokens,
            max_session_notes=harness.max_session_notes,
            history_keep_recent=harness.history_keep_recent,
            nudge_interval=harness.nudge_interval,
            max_consecutive_errors=harness.max_consecutive_errors,
            compaction_thresholds=harness.compaction_thresholds,
        )
        for turn in initial_history:
            self._state.append_turn(turn)
        self._events: list[Event] = []

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    async def run_stream(self, query: str) -> AsyncIterator[Event]:
        """Stream events for a single query to completion.

        Appends the user query as a Turn, then drives ``run_loop`` until it
        emits a terminal event. ``state.iterations`` is reset per call so
        ``max_iterations`` is a per-query budget, not a per-session one.
        """
        self._state.append_turn(Turn(role="user", content=query))
        async for event in run_loop(
            self._state,
            session_id=self.id,
            cache=self._cache,
            default_char_limit=self.harness.max_tool_result_chars,
            char_limits=self.harness.tool_result_char_limits,
            seq_start=len(self._events),
        ):
            self._events.append(event)
            yield event

    async def run(self, query: str) -> FinalAnswerEvent:
        """Drain ``run_stream`` and return the final answer.

        One implementation, zero duplication with the streaming path. If the
        loop terminates without a ``FinalAnswerEvent`` (e.g. clarification or
        unrecoverable error), raises ``RuntimeError`` — the streaming API is
        the right tool for those cases.
        """
        final: FinalAnswerEvent | None = None
        async for event in self.run_stream(query):
            if isinstance(event, FinalAnswerEvent):
                final = event
        if final is None:
            raise RuntimeError(
                "loop ended without a FinalAnswerEvent; use run_stream() to "
                "observe clarification or error events"
            )
        return final

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------
    def history(self) -> list[Turn]:
        return list(self._state.history)

    def notes(self) -> list[Note]:
        return list(self._state.notes)

    def events(self) -> list[Event]:
        return list(self._events)

    # ------------------------------------------------------------------
    # Forking
    # ------------------------------------------------------------------
    def fork(self, at_turn: int = -1) -> Session:
        """Branch from this session at ``at_turn``.

        ``at_turn=-1`` (default) forks from the current tail. Otherwise the
        new session inherits ``history[:at_turn]``. The fork gets a fresh
        cache and event log; ``parent_id`` points back to this session for
        the session tree (T-23).
        """
        history = list(self._state.history)
        if at_turn >= 0:
            history = history[:at_turn]
        return Session(
            harness=self.harness,
            session_id=uuid.uuid4().hex,
            parent_id=self.id,
            initial_history=history,
        )

    # ------------------------------------------------------------------
    # Stubs — land in later tasks
    # ------------------------------------------------------------------
    async def steer(self, message: str, mode: SteeringMode = "interrupt") -> None:
        raise NotImplementedError("steering wiring lands with T-06")

    def save(self) -> None:
        raise NotImplementedError("session persistence lands with T-23")

    @classmethod
    def load(cls, session_id: str) -> Session:
        raise NotImplementedError("session persistence lands with T-23")


__all__ = ["Harness", "Profile", "Session"]
