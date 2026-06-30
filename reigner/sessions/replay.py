"""Deterministic session reconstruction.

Rebuild an :class:`~reigner.harness.state.AgentState` from a session's event
log — history, scratchpad notes, and citations — *without calling any model
provider*. This is the engine behind resume (``Session.load``), fork-from-disk,
and live re-run (``Session.replay``).

How it works
------------
The honest way to reproduce a session's in-memory state is to run the *real*
:func:`reigner.harness.loop.run_loop` again, because that loop is the single
source of truth for how history is shaped, when nudges fire, and when
compaction kicks in. We feed it two stand-ins:

- a :class:`_StubAdapter` that replays the ``ModelAction`` for each iteration,
  reconstructed from the recorded ``ToolCallEvent`` / ``FinalAnswerEvent`` rows;
- a registry of stub tools that return the recorded ``ToolResultEvent`` payload
  for each call instead of hitting a real tool.

Pseudo-tools (``save_note``, ``register_citation``, ``escalate_to_oracle``,
``stop``, ``request_clarification``) are *not* stubbed — the loop dispatches
them inline, so replaying their ``ToolCallEvent``s rebuilds notes/citations and
terminal state for free.

Known fidelity gaps (documented, accepted for v0)
-------------------------------------------------
- **Assistant text alongside tool calls** is never logged by any event, so it
  can't be recovered. Tool calls, results, and queries all survive.
- **Steering** messages are re-enqueued at the *start* of the round they
  belonged to; steering consumed deep inside a round is re-placed slightly
  earlier. The message content and all model/tool turns are preserved.
- **Compaction timing** can differ marginally: the recorded log doesn't carry
  the original tool *schemas*, so the stable-prompt token count (and thus the
  pressure thresholds) is approximate. Sessions that never compacted are exact.
- **Error-driven nudges**: ``ToolResultEvent`` carries no ``errored`` flag, so
  a recorded result is replayed as a success. Consecutive-error nudges may not
  reproduce for sessions that hit tool failures.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from reigner.harness.adapters.base import ModelAction, ToolCall, TransientAdapterError
from reigner.harness.cache import ToolResultCache
from reigner.harness.events import (
    Event,
    FinalAnswerEvent,
    SteeringAcceptedEvent,
    ToolCallEvent,
    ToolResultEvent,
    UserQueryEvent,
)
from reigner.harness.loop import INTERCEPTED_TOOL_NAMES, run_loop
from reigner.harness.state import AgentState, SteeringMode, Turn
from reigner.tools.base import ToolSpec
from reigner.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine, Sequence

    from reigner.config import SettingsConfig
    from reigner.harness.state import Prompt


class ReplayError(ValueError):
    """Raised when an event log can't be reconstructed.

    The common case: a session recorded under SCHEMA_VERSION 1 (before
    ``UserQueryEvent``) has no query rows, so there's nothing to seed a round
    from. Such sessions remain inspectable via ``Session.events()`` but cannot
    be reconstructed, forked, or replayed.
    """


# ---------------------------------------------------------------------------
# Round segmentation
# ---------------------------------------------------------------------------


def round_boundaries(events: Sequence[Event]) -> list[int]:
    """Indices of every ``UserQueryEvent`` — one per conversational round.

    ``at_turn=N`` (1-based) refers to ``round_boundaries(events)[N - 1]``.
    """
    return [i for i, ev in enumerate(events) if isinstance(ev, UserQueryEvent)]


def _argkey(args: dict[str, Any]) -> str:
    """Stable key for a tool call's args. Mirrors the cache's (name, args) key."""
    return json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)


# ---------------------------------------------------------------------------
# Event log → ModelActions (the regrouper)
# ---------------------------------------------------------------------------


def _round_to_actions(round_events: Sequence[Event]) -> list[ModelAction]:
    """Rebuild the per-iteration ``ModelAction``s the loop produced in one round.

    Group by the event ``turn`` field (the loop's per-iteration counter, which
    resets to 0 at the start of each round). Each iteration is either a batch of
    tool calls or a final answer.
    """
    by_turn: dict[int, list[Event]] = defaultdict(list)
    for ev in round_events:
        by_turn[ev.turn].append(ev)

    actions: list[ModelAction] = []
    for turn in sorted(by_turn):
        bucket = by_turn[turn]
        calls = [
            ToolCall(id=e.call_id, name=e.name, args=e.args)
            for e in bucket
            if isinstance(e, ToolCallEvent)
        ]
        final = next((e for e in bucket if isinstance(e, FinalAnswerEvent)), None)
        # Locally intercepted terminal tools (notably ``stop``) emit a
        # FinalAnswerEvent on the same turn as their ToolCallEvent. Replaying
        # the call regenerates that terminal event and preserves tool history.
        if calls:
            actions.append(ModelAction(is_final_answer=False, tool_calls=calls))
        elif final is not None:
            actions.append(ModelAction(is_final_answer=True, text=final.text))
    return actions


# ---------------------------------------------------------------------------
# Stub adapter + stub tools
# ---------------------------------------------------------------------------


@dataclass
class _StubAdapter:
    """Replays a scripted list of ``ModelAction``s, one per ``call``.

    Set :attr:`actions` before each round. When exhausted it raises a transient
    adapter error so the loop terminates the way it would on a provider failure
    (covers rounds that originally ended mid-flight).
    """

    name: str = "replay-stub"
    model: str = "replay"
    supports_prompt_caching: bool = False
    actions: list[ModelAction] = field(default_factory=list)
    _cursor: int = 0

    def load(self, actions: list[ModelAction]) -> None:
        self.actions = actions
        self._cursor = 0

    async def call(self, prompt: Prompt, tools: list[Any]) -> ModelAction:
        if self._cursor >= len(self.actions):
            raise TransientAdapterError("replay: scripted actions exhausted")
        action = self.actions[self._cursor]
        self._cursor += 1
        return action


def _stub_tool_func(results: dict[str, deque[Any]]) -> Callable[..., Awaitable[Any]]:
    """Build an async stub that returns the recorded result for its args."""

    async def _run(**kwargs: Any) -> Any:
        key = _argkey(kwargs)
        if key in results and results[key]:
            return results[key].popleft()
        # Arg-key miss (shouldn't happen — replayed args are byte-identical to
        # the recorded ones). Fall back to any recorded result so the loop still
        # completes rather than stalling on a missing tool.
        for queued in results.values():
            if queued:
                return queued.popleft()
        return {"error": "reigner-replay: no recorded result"}

    return _run


def _build_stub_results(events: Sequence[Event]) -> dict[str, dict[str, deque[Any]]]:
    """Map real tools and args to ordered queues of their recorded results.

    Pairs each ``ToolCallEvent`` with its ``ToolResultEvent`` by ``call_id``.
    Intercepted verbs (pseudo + provenance) are skipped — the loop handles them
    inline, so they never reach a stub tool. Queues preserve multiple different
    results from repeated calls with identical arguments.
    """
    pending: dict[str, tuple[str, dict[str, Any]]] = {}  # call_id -> (name, args)
    grouped: dict[str, dict[str, deque[Any]]] = defaultdict(lambda: defaultdict(deque))
    for ev in events:
        if isinstance(ev, ToolCallEvent) and ev.name not in INTERCEPTED_TOOL_NAMES:
            pending[ev.call_id] = (ev.name, ev.args)
        elif isinstance(ev, ToolResultEvent) and ev.call_id in pending:
            name, args = pending.pop(ev.call_id)
            grouped[name][_argkey(args)].append(ev.result)
    return {name: dict(results) for name, results in grouped.items()}


def _build_stub_registry(events: Sequence[Event]) -> ToolRegistry:
    """A registry of non-caching stub tools, one per real tool name in the log.

    Reconstruction must consume the recorded result for each call. Marking
    stubs readonly would let the live G9 cache collapse repeated equal-argument
    calls even when their recorded values differ.
    """
    registry = ToolRegistry()
    for name, results in _build_stub_results(events).items():
        spec = ToolSpec(
            name=name,
            description="(reigner replay stub)",
            readonly=False,
            pseudo=False,
            cache=False,
            truncate_chars=None,
            func=_stub_tool_func(results),
            schema={"type": "object"},
        )
        registry.register(spec)
    return registry


# ---------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------


async def areconstruct(
    events: Sequence[Event],
    *,
    settings: SettingsConfig,
    session_id: str,
    role: str = "",
) -> AgentState:
    """Rebuild the ``AgentState`` a session ended in, by replaying its log.

    Drives the real :func:`run_loop` once per round against a stub adapter and
    stub tools. The returned state carries the reconstructed history, notes, and
    citations; its ``registry``/``adapter`` are stubs and must be swapped for a
    live ``Harness``'s before the session can run new turns (callers do this by
    seeding a fresh ``Session``'s state from the three lists).
    """
    events = list(events)
    bounds = round_boundaries(events)
    if not bounds and events:
        raise ReplayError(
            f"session {session_id!r} has events but no UserQueryEvent — it predates "
            "SCHEMA_VERSION 2 and cannot be reconstructed (inspect events() instead)."
        )

    stub = _StubAdapter()
    state = AgentState(
        session_id=session_id,
        role=role,
        registry=_build_stub_registry(events),
        profile="full",
        adapter=stub,
        oracle_adapter=stub,
        max_iterations=settings.max_iterations,
        context_budget_tokens=settings.context_budget_tokens,
        max_session_notes=settings.max_session_notes,
        history_keep_recent=settings.history_keep_recent,
        nudge_interval=settings.nudge_interval,
        max_consecutive_errors=settings.max_consecutive_errors,
        compaction_thresholds=settings.compaction_thresholds,
    )
    cache = ToolResultCache()

    for i, start in enumerate(bounds):
        end = bounds[i + 1] if i + 1 < len(bounds) else len(events)
        round_events = events[start + 1 : end]
        query = cast(UserQueryEvent, events[start]).query

        # Re-enqueue this round's steering so the loop reproduces those user
        # turns (best-effort placement: at the round's first iteration).
        for ev in round_events:
            if isinstance(ev, SteeringAcceptedEvent):
                state.enqueue_steering(ev.message, cast(SteeringMode, ev.mode))

        state.append_turn(Turn(role="user", content=query))
        stub.load(_round_to_actions(round_events))
        async for _ in run_loop(
            state,
            session_id=session_id,
            cache=cache,
            default_char_limit=settings.max_tool_result_chars,
            char_limits=settings.tool_result_char_limits,
        ):
            pass  # events are discarded — we only want the side effects on `state`

    return state


def reconstruct(
    events: Sequence[Event],
    *,
    settings: SettingsConfig,
    session_id: str,
    role: str = "",
) -> AgentState:
    """Synchronous wrapper around :func:`areconstruct`.

    ``Session.load`` / ``Session.fork`` are sync, but the loop is
    async. We run the coroutine to completion on a private event loop: directly
    via ``asyncio.run`` when no loop is running, otherwise on a worker thread so
    the call is safe from inside ``async`` code (e.g. async tests). The
    reconstruction is fully self-contained (stub adapter/tools, no shared I/O),
    so a separate loop is harmless.
    """
    return _run_coro_sync(areconstruct(events, settings=settings, session_id=session_id, role=role))


def _run_coro_sync(coro: Coroutine[Any, Any, AgentState]) -> AgentState:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


__all__ = [
    "ReplayError",
    "areconstruct",
    "reconstruct",
    "round_boundaries",
]
