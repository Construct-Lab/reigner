"""The agent loop. The opinionated, non-negotiable core (SPEC.md §5.3).

A single ``async def run_loop(state) -> AsyncIterator[Event]``. Each yield is
a checkpoint where the caller can stop iterating — cancelling the iterator
cancels the loop. No background tasks, no speculative work; one iteration is
one model call, visible to the caller via the event stream.

Guardrails owned here (others land in their own modules as later tasks):

- G1 — stable/dynamic prompt boundary: ``state.build_prompt`` (already in T-03).
- G2 — per-tool truncation: ``truncation.truncate_for_tool`` (stub in T-05).
- G3/G4 — iteration / consecutive-error nudges: stubbed; T-08 will replace the
  early-stop break with a real injected nudge.
- G5/G10 — history + progressive compaction: T-08; the loop currently emits no
  ``CompactionEvent``s rather than emit ones it can't honour.
- G6/G7 — dynamic context refresh: ``state.refresh_context`` (T-03).
- G8 — scratchpad: ``save_note`` pseudo-tool branch.
- G9 — tool-result cache: ``cache.ToolResultCache`` (stub in T-05).
- G11 — parallel reads: ``asyncio.gather`` when every real call this turn is
  ``readonly=True``.

Pseudo-tools are dispatched inline, hardcoded — not registered through any
plugin surface — so a reader of this file sees every special case in one place.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any, Protocol, runtime_checkable

from reigner.harness.adapters.base import (
    AdapterError,
    ModelAction,
    ModelAdapter,
    ToolCall,
    TransientAdapterError,
)
from reigner.harness.cache import ToolResultCache
from reigner.harness.events import (
    ClarificationEvent,
    ErrorEvent,
    Event,
    FinalAnswerEvent,
    OracleEscalationEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from reigner.harness.state import AgentState, ToolSpec, Turn
from reigner.harness.truncation import truncate_for_tool


@runtime_checkable
class RunnableTool(ToolSpec, Protocol):
    """Loop-side tool contract: a ToolSpec that can be invoked.

    T-07's ``tools/base.py`` will own the canonical ``Tool`` type. We declare
    the minimum runtime surface here so the loop can stay decoupled from the
    full tool registry that lands later.
    """

    async def run(self, args: dict[str, Any]) -> Any: ...


PSEUDO_TOOL_NAMES = frozenset({"save_note", "request_clarification", "stop", "escalate_to_oracle"})


def _content_for_history(value: Any) -> str:
    """Serialize a tool result into a string the adapter can put in history."""
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


async def run_loop(  # noqa: C901, PLR0912, PLR0915 — legibility > splitting; SPEC §5.3
    state: AgentState,
    *,
    session_id: str,
    cache: ToolResultCache,
    default_char_limit: int = 4000,
    char_limits: dict[str, int] | None = None,
    seq_start: int = 0,
) -> AsyncIterator[Event]:
    """Drive one query to completion. Yields events in emission order.

    The loop assumes ``state.history`` already has the user query appended.
    It mutates ``state`` in place (history, notes, iterations, error counter)
    and emits exactly one terminal event per call: ``FinalAnswerEvent``,
    ``ClarificationEvent``, or ``ErrorEvent``.
    """
    char_limits = char_limits or {}
    tools_by_name: dict[str, RunnableTool] = {
        t.name: t for t in state.tools if isinstance(t, RunnableTool)
    }

    # Per-call iteration counter (max_iterations is a per-query budget).
    state.iterations = 0
    state.done = False

    seq = seq_start

    def next_seq() -> int:
        nonlocal seq
        v = seq
        seq += 1
        return v

    if state.adapter is None:
        yield ErrorEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            error="no model adapter configured on AgentState",
            recoverable=False,
        )
        return

    # state.adapter is typed against the structural stub in state.py; the loop
    # depends on the richer adapters.base.ModelAdapter (which has .call()).
    adapter: ModelAdapter = state.adapter  # type: ignore[assignment]

    while not state.done:
        state.refresh_context()

        # G5/G10: compaction belongs to T-08. Read pressure here so the hook
        # surface is in place; do not emit a CompactionEvent until it actually
        # frees tokens.
        _ = state.context_pressure()

        prompt = state.build_prompt()

        try:
            action: ModelAction = await adapter.call(prompt, list(state.tools))
        except AdapterError as exc:
            recoverable = isinstance(exc, TransientAdapterError)
            state.record_tool_error()
            yield ErrorEvent(
                seq=next_seq(),
                session_id=session_id,
                turn=state.iterations,
                error=f"adapter: {exc}",
                recoverable=recoverable,
            )
            # Don't keep hammering a broken provider.
            return

        # ----- terminal: explicit final answer -----
        if action.is_final_answer:
            text = action.text or ""
            state.append_turn(Turn(role="assistant", content=text))
            yield FinalAnswerEvent(
                seq=next_seq(),
                session_id=session_id,
                turn=state.iterations,
                text=text,
                metadata={"usage": asdict(action.usage), "stop_reason": action.stop_reason},
            )
            state.done = True
            return

        # ----- terminal: no progress (no text, no calls) -----
        if not action.tool_calls:
            text = action.text or ""
            state.append_turn(Turn(role="assistant", content=text))
            yield FinalAnswerEvent(
                seq=next_seq(),
                session_id=session_id,
                turn=state.iterations,
                text=text,
                metadata={
                    "usage": asdict(action.usage),
                    "stop_reason": action.stop_reason,
                    "no_progress": True,
                },
            )
            state.done = True
            return

        # Record the assistant turn carrying the tool calls.
        state.append_turn(
            Turn(
                role="assistant",
                content=action.text or "",
                tool_calls=[
                    {"id": tc.id, "name": tc.name, "args": tc.args} for tc in action.tool_calls
                ],
            )
        )

        # Decide parallel vs serial for the *real* tool calls this turn.
        # G11: only when every real call is readonly. Pseudo-tools always run
        # serially since some terminate the loop.
        real_calls = [tc for tc in action.tool_calls if tc.name not in PSEUDO_TOOL_NAMES]
        all_readonly = bool(real_calls) and all(
            tools_by_name.get(tc.name) is not None and tools_by_name[tc.name].readonly
            for tc in real_calls
        )

        # Process every call in original order. Pseudo-tools dispatch inline
        # (and may set state.done); real calls collect into a batch we either
        # gather or run serially based on `all_readonly`.
        terminate_after_calls = False
        pending_real: list[ToolCall] = []

        for tc in action.tool_calls:
            if tc.name in PSEUDO_TOOL_NAMES:
                # Flush any queued real calls first so emission order is stable.
                if pending_real:
                    async for ev in _run_real_calls(
                        pending_real,
                        tools_by_name=tools_by_name,
                        cache=cache,
                        state=state,
                        session_id=session_id,
                        default_char_limit=default_char_limit,
                        char_limits=char_limits,
                        parallel=all_readonly,
                        next_seq=next_seq,
                    ):
                        yield ev
                    pending_real = []

                async for ev in _dispatch_pseudo(
                    tc,
                    state=state,
                    session_id=session_id,
                    next_seq=next_seq,
                ):
                    yield ev
                if state.done:
                    terminate_after_calls = True
                    break
            else:
                pending_real.append(tc)

        if pending_real and not terminate_after_calls:
            async for ev in _run_real_calls(
                pending_real,
                tools_by_name=tools_by_name,
                cache=cache,
                state=state,
                session_id=session_id,
                default_char_limit=default_char_limit,
                char_limits=char_limits,
                parallel=all_readonly,
                next_seq=next_seq,
            ):
                yield ev

        if terminate_after_calls:
            return

        # G4: too many consecutive errors → bail out. T-08 will replace this
        # with an injected nudge that asks the model to wrap up gracefully.
        if state.consecutive_errors() >= state.max_consecutive_errors:
            yield ErrorEvent(
                seq=next_seq(),
                session_id=session_id,
                turn=state.iterations,
                error=f"aborted: {state.consecutive_errors()} consecutive tool errors",
                recoverable=False,
            )
            return

        state.iterations += 1

        if state.iterations >= state.max_iterations:
            yield ErrorEvent(
                seq=next_seq(),
                session_id=session_id,
                turn=state.iterations,
                error="max_iterations reached without a final answer",
                recoverable=False,
            )
            return


# ---------------------------------------------------------------------------
# Pseudo-tool dispatch
# ---------------------------------------------------------------------------


async def _dispatch_pseudo(
    tc: ToolCall,
    *,
    state: AgentState,
    session_id: str,
    next_seq: Any,
) -> AsyncIterator[Event]:
    """Handle a pseudo-tool call. May set ``state.done``.

    Pseudo-tools are intercepted locally — they never reach an external
    service. See SPEC §6.4.
    """
    yield ToolCallEvent(
        seq=next_seq(),
        session_id=session_id,
        turn=state.iterations,
        name=tc.name,
        args=tc.args,
        call_id=tc.id,
    )

    if tc.name == "save_note":
        text = str(tc.args.get("text", ""))
        state.add_note(text)
        result = {"ok": True}
        state.append_turn(
            Turn(role="tool", content=_content_for_history(result), tool_call_id=tc.id)
        )
        yield ToolResultEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            call_id=tc.id,
            result=result,
            truncated=False,
            cached=False,
        )
        return

    if tc.name == "request_clarification":
        yield ClarificationEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            question=str(tc.args.get("question", "")),
            candidates=list(tc.args.get("candidates", []) or []),
        )
        state.done = True
        return

    if tc.name == "stop":
        reason = str(tc.args.get("reason", ""))
        state.append_turn(Turn(role="assistant", content=reason))
        yield FinalAnswerEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            text=reason,
            metadata={"stop": True},
        )
        state.done = True
        return

    if tc.name == "escalate_to_oracle":
        # T-05 deferred wiring (see issue #5 brainstorm). Emit the event so
        # plugins/eval can observe the request, but execute as a no-op.
        from_model = state.adapter.model if state.adapter is not None else "unknown"
        to_model = state.oracle_adapter.model if state.oracle_adapter is not None else "(deferred)"
        yield OracleEscalationEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            reason=str(tc.args.get("reason", "")),
            from_model=from_model,
            to_model=to_model,
        )
        oracle_result: dict[str, Any] = {"ok": True, "note": "oracle escalation deferred"}
        state.append_turn(
            Turn(role="tool", content=_content_for_history(oracle_result), tool_call_id=tc.id)
        )
        yield ToolResultEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            call_id=tc.id,
            result=oracle_result,
            truncated=False,
            cached=False,
        )
        return

    # Unreachable: caller filtered on PSEUDO_TOOL_NAMES.
    raise AssertionError(f"unhandled pseudo-tool: {tc.name}")


# ---------------------------------------------------------------------------
# Real tool execution (G9 cache + G11 parallel)
# ---------------------------------------------------------------------------


async def _execute_one(
    tc: ToolCall,
    *,
    tool: RunnableTool | None,
    cache: ToolResultCache,
) -> tuple[Any, bool, bool]:
    """Run one real tool call. Returns ``(raw_result, cache_hit, errored)``.

    Cache hits skip execution entirely. Cache misses store *successful*
    results only — we don't memoize errors, since the next call may succeed.
    """
    if tool is None:
        return {"error": f"unknown tool: {tc.name}"}, False, True

    if tool.readonly and cache.has(tc.name, tc.args):
        return cache.get(tc.name, tc.args), True, False

    try:
        raw = await tool.run(tc.args)
    except Exception as exc:  # noqa: BLE001 — tool errors get reported to the model
        return {"error": f"{type(exc).__name__}: {exc}"}, False, True

    if tool.readonly:
        cache.put(tc.name, tc.args, raw)
    return raw, False, False


async def _run_real_calls(
    calls: list[ToolCall],
    *,
    tools_by_name: dict[str, RunnableTool],
    cache: ToolResultCache,
    state: AgentState,
    session_id: str,
    default_char_limit: int,
    char_limits: dict[str, int],
    parallel: bool,
    next_seq: Any,
) -> AsyncIterator[Event]:
    """Emit ToolCall/ToolResult events for a batch of real tool calls.

    Order: every ``ToolCallEvent`` is emitted first (matching the order the
    model issued them), then results are emitted in the same order. When
    ``parallel`` is True the ``_execute_one`` calls are gathered concurrently
    but the event stream stays deterministic.
    """
    for tc in calls:
        yield ToolCallEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            name=tc.name,
            args=tc.args,
            call_id=tc.id,
        )

    if parallel and len(calls) > 1:
        results = await asyncio.gather(
            *(_execute_one(tc, tool=tools_by_name.get(tc.name), cache=cache) for tc in calls)
        )
    else:
        results = []
        for tc in calls:
            results.append(await _execute_one(tc, tool=tools_by_name.get(tc.name), cache=cache))

    for tc, (raw, cache_hit, errored) in zip(calls, results, strict=True):
        if errored:
            state.record_tool_error()
        else:
            state.record_tool_success()

        limit = char_limits.get(tc.name, default_char_limit)
        truncated, was_truncated = truncate_for_tool(raw, limit)

        state.append_turn(
            Turn(
                role="tool",
                content=_content_for_history(truncated),
                tool_call_id=tc.id,
            )
        )

        yield ToolResultEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            call_id=tc.id,
            result=truncated,
            truncated=was_truncated,
            cached=cache_hit,
        )


__all__ = [
    "PSEUDO_TOOL_NAMES",
    "RunnableTool",
    "run_loop",
]
