"""The agent loop. The opinionated, non-negotiable core (SPEC.md §5.3).

A single ``async def run_loop(state) -> AsyncIterator[Event]``. Each yield is
a checkpoint where the caller can stop iterating — cancelling the iterator
cancels the loop. No background tasks, no speculative work; one iteration is
one model call, visible to the caller via the event stream.

Guardrails wired here (each lives in its own module — see SPEC §5.4):

- G1 — stable/dynamic prompt boundary: ``state.build_prompt``.
- G2 — per-tool truncation: ``truncation.truncate_for_tool``.
- G3 — iteration nudges: ``nudges.iteration_nudge`` injected each iteration.
- G4 — consecutive-error nudge: ``nudges.error_nudge`` injected before the
  loop hard-aborts on repeated failure.
- G5/G10 — history + progressive compaction: ``compaction.progressive``,
  emits ``CompactionEvent`` when a tier fires.
- G6/G7 — dynamic context refresh: ``state.refresh_context``.
- G8 — scratchpad: ``save_note`` pseudo-tool branch (state survives compaction).
- G9 — tool-result cache: ``cache.ToolResultCache`` consulted in ``parallel``.
- G11 — parallel reads: ``parallel.execute_batch`` gathers concurrently when
  every real call this turn is ``readonly=True``.

Oracle escalation (SPEC §5.5) lives in ``oracle.py``; ``pick_adapter`` is
called per-iteration so the swap is single-turn.

Steering (SPEC §5.6) is drained at the top of each iteration: queued user
messages are appended as ``user`` turns so the next ``adapter.call`` sees
them, and a ``SteeringAcceptedEvent`` is emitted per drained message. The
iteration boundary *is* the "next tool boundary" §5.6 refers to — by the
time control reaches the drain point, any prior turn's tool calls have
already completed.

Pseudo-tools are dispatched inline, hardcoded — not registered through any
plugin surface — so a reader of this file sees every special case in one place.
"""

from __future__ import annotations

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
from reigner.harness.compaction import progressive
from reigner.harness.events import (
    CitationEvent,
    ClarificationEvent,
    CompactionEvent,
    ErrorEvent,
    Event,
    FinalAnswerEvent,
    OracleEscalationEvent,
    SteeringAcceptedEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from reigner.harness.nudges import error_nudge, iteration_nudge
from reigner.harness.oracle import OracleNotConfigured, pick_adapter
from reigner.harness.oracle import arm as oracle_arm
from reigner.harness.parallel import execute_batch, should_parallelize
from reigner.harness.state import AgentState, Citation, Turn
from reigner.harness.truncation import resolve_limit, truncate_for_tool
from reigner.plugins.hooks import PluginHookError
from reigner.plugins.host import PluginHost
from reigner.tools.provenance import PROVENANCE_TOOL_NAMES, citation_id
from reigner.tools.pseudo import PSEUDO_TOOL_NAMES

# All tool names the loop intercepts locally — pseudo loop-management verbs
# plus the provenance tools. Real tools (anything not in this union) go
# through the standard execute path.
INTERCEPTED_TOOL_NAMES: frozenset[str] = PSEUDO_TOOL_NAMES | PROVENANCE_TOOL_NAMES


@runtime_checkable
class RunnableTool(Protocol):
    """Loop-side tool contract: anything with a name and an awaitable ``run``.

    Concretely satisfied by ``RunnableToolAdapter`` (which wraps a ToolSpec).
    The loop never indexes adapters by anything other than name + ``.run()``,
    so this Protocol is intentionally thin. ``name``/``readonly`` are declared
    as ``@property`` so adapters whose attributes are read-only descriptors
    structurally match.
    """

    @property
    def name(self) -> str: ...

    @property
    def readonly(self) -> bool: ...

    async def run(self, args: dict[str, Any]) -> Any: ...


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
    plugins: PluginHost | None = None,
) -> AsyncIterator[Event]:
    """Drive one query to completion. Yields events in emission order.

    The loop assumes ``state.history`` already has the user query appended.
    It mutates ``state`` in place (history, notes, iterations, error counter)
    and emits exactly one terminal event per call: ``FinalAnswerEvent``,
    ``ClarificationEvent``, or ``ErrorEvent``.

    ``plugins`` is the :class:`PluginHost` whose hooks fire around the loop
    (SPEC §12). Transform hooks (``before_tool_call``, ``after_tool_call``,
    ``on_final_answer``) can rewrite what flows through; a failure there is
    fatal and surfaces as an ``ErrorEvent``. Observe hooks fire at the matching
    event sites and never abort the run. Defaults to a no-op host.
    """
    char_limits = char_limits or {}
    if plugins is None:
        plugins = PluginHost.empty()
    # Profile is fixed for the session's lifetime; one filter call gives us
    # both the adapter list passed to the model and the dispatch map. Pseudo
    # tools never enter `tools_by_name` because real-vs-pseudo branching
    # happens later via `PSEUDO_TOOL_NAMES`.
    runnables = state.registry.for_profile(state.profile)
    tools_by_name: dict[str, RunnableTool] = {a.name: a for a in runnables}

    # Per-call iteration counter (max_iterations is a per-query budget).
    state.iterations = 0
    state.done = False

    seq = seq_start

    def next_seq() -> int:
        nonlocal seq
        v = seq
        seq += 1
        return v

    def plugin_error(exc: PluginHookError) -> ErrorEvent:
        # A transform hook failed (SPEC §12): fail loud, abort the run.
        return ErrorEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            error=f"plugin: {exc}",
            recoverable=False,
        )

    if state.adapter is None:
        no_adapter = ErrorEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            error="no model adapter configured on AgentState",
            recoverable=False,
        )
        await plugins.on_error(no_adapter, state)
        yield no_adapter
        return

    while not state.done:
        # Pick per-iteration so single-turn oracle escalation (SPEC §5.5)
        # transparently swaps in state.oracle_adapter and reverts after one call.
        adapter: ModelAdapter = pick_adapter(state)
        state.refresh_context()

        # SPEC §5.6: drain queued steering messages before building the next
        # prompt so the model sees them on its very next call. Both modes drop
        # in here — at this point any prior turn's tool calls have already
        # completed, so "interrupt" and "queue" converge on append-as-user-turn.
        if state.has_pending_steering():
            for message, mode in state.consume_steering():
                state.append_turn(Turn(role="user", content=message))
                steering_event = SteeringAcceptedEvent(
                    seq=next_seq(),
                    session_id=session_id,
                    turn=state.iterations,
                    message=message,
                    mode=mode,
                )
                await plugins.on_steering(steering_event, state)
                yield steering_event

        # G5/G10: progressive compaction at 80/90/95% of the token budget.
        outcome = progressive(state)
        if outcome.level is not None:
            await plugins.on_compaction(state, outcome.level)
            yield CompactionEvent(
                seq=next_seq(),
                session_id=session_id,
                turn=state.iterations,
                level=outcome.level,
                tokens_freed=outcome.tokens_freed,
            )

        # G3: inject a strategic nudge every nudge_interval iterations. The
        # nudge is a synthetic user-role turn the model sees on its next call.
        nudge = iteration_nudge(state)
        if nudge is not None:
            state.append_turn(Turn(role="user", content=nudge))

        prompt = state.build_prompt()

        try:
            action: ModelAction = await adapter.call(prompt, [a.spec for a in runnables])
        except AdapterError as exc:
            recoverable = isinstance(exc, TransientAdapterError)
            state.record_tool_error()
            adapter_error = ErrorEvent(
                seq=next_seq(),
                session_id=session_id,
                turn=state.iterations,
                error=f"adapter: {exc}",
                recoverable=recoverable,
            )
            await plugins.on_error(adapter_error, state)
            yield adapter_error
            # Don't keep hammering a broken provider.
            return

        # ----- terminal: explicit final answer -----
        if action.is_final_answer:
            final = FinalAnswerEvent(
                seq=next_seq(),
                session_id=session_id,
                turn=state.iterations,
                text=action.text or "",
                metadata={"usage": asdict(action.usage), "stop_reason": action.stop_reason},
            )
            try:
                final = await plugins.on_final_answer(final, state)
            except PluginHookError as exc:
                err = plugin_error(exc)
                await plugins.on_error(err, state)
                yield err
                return
            # History reflects the post-hook text so a rewrite sticks.
            state.append_turn(Turn(role="assistant", content=final.text))
            yield final
            state.done = True
            return

        # ----- terminal: no progress (no text, no calls) -----
        if not action.tool_calls:
            final = FinalAnswerEvent(
                seq=next_seq(),
                session_id=session_id,
                turn=state.iterations,
                text=action.text or "",
                metadata={
                    "usage": asdict(action.usage),
                    "stop_reason": action.stop_reason,
                    "no_progress": True,
                },
            )
            try:
                final = await plugins.on_final_answer(final, state)
            except PluginHookError as exc:
                err = plugin_error(exc)
                await plugins.on_error(err, state)
                yield err
                return
            state.append_turn(Turn(role="assistant", content=final.text))
            yield final
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
        real_calls = [tc for tc in action.tool_calls if tc.name not in INTERCEPTED_TOOL_NAMES]
        all_readonly = should_parallelize(real_calls, tools_by_name)

        # Process every call in original order. Pseudo-tools dispatch inline
        # (and may set state.done); real calls collect into a batch we either
        # gather or run serially based on `all_readonly`.
        terminate_after_calls = False
        pending_real: list[ToolCall] = []

        for tc in action.tool_calls:
            if tc.name in INTERCEPTED_TOOL_NAMES:
                # Flush any queued real calls first so emission order is stable.
                if pending_real:
                    try:
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
                            plugins=plugins,
                        ):
                            yield ev
                    except PluginHookError as exc:
                        err = plugin_error(exc)
                        await plugins.on_error(err, state)
                        yield err
                        return
                    pending_real = []

                try:
                    async for ev in _dispatch_pseudo(
                        tc,
                        state=state,
                        session_id=session_id,
                        next_seq=next_seq,
                        plugins=plugins,
                    ):
                        yield ev
                except PluginHookError as exc:
                    err = plugin_error(exc)
                    await plugins.on_error(err, state)
                    yield err
                    return
                if state.done:
                    terminate_after_calls = True
                    break
            else:
                pending_real.append(tc)

        if pending_real and not terminate_after_calls:
            try:
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
                    plugins=plugins,
                ):
                    yield ev
            except PluginHookError as exc:
                err = plugin_error(exc)
                await plugins.on_error(err, state)
                yield err
                return

        if terminate_after_calls:
            return

        # G4: at the consecutive-error threshold, inject a wrap-up nudge once
        # and let the model produce a final answer. If errors keep coming
        # after the nudge, bail with an ErrorEvent.
        err_msg = error_nudge(state)
        if err_msg is not None:
            if not state.error_nudge_injected:
                state.append_turn(Turn(role="user", content=err_msg))
                state.error_nudge_injected = True
            else:
                abort_error = ErrorEvent(
                    seq=next_seq(),
                    session_id=session_id,
                    turn=state.iterations,
                    error=(
                        f"aborted: {state.consecutive_errors()} consecutive tool errors after nudge"
                    ),
                    recoverable=False,
                )
                await plugins.on_error(abort_error, state)
                yield abort_error
                return

        state.iterations += 1

        if state.iterations >= state.max_iterations:
            max_iter_error = ErrorEvent(
                seq=next_seq(),
                session_id=session_id,
                turn=state.iterations,
                error="max_iterations reached without a final answer",
                recoverable=False,
            )
            await plugins.on_error(max_iter_error, state)
            yield max_iter_error
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
    plugins: PluginHost,
) -> AsyncIterator[Event]:
    """Handle a pseudo-tool call. May set ``state.done``.

    Pseudo-tools are intercepted locally — they never reach an external
    service. See SPEC §6.4.

    Pseudo-tools are not wrapped by ``before_tool_call`` / ``after_tool_call``
    (those fire for real tools only). The two pseudo verbs that map to a
    dedicated hook do fire it: ``escalate_to_oracle`` → ``on_oracle_escalation``
    and ``stop`` → ``on_final_answer``. A failing ``on_final_answer`` raises
    :class:`PluginHookError` for the caller to convert into an ``ErrorEvent``.
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

    if tc.name == "register_citation":
        source = str(tc.args.get("source", ""))
        raw_locator = tc.args.get("locator", {}) or {}
        locator: dict[str, Any] = (
            dict(raw_locator) if isinstance(raw_locator, dict) else {"_": str(raw_locator)}
        )
        value = tc.args.get("value")
        citation = Citation(
            source=source,
            locator=locator,
            value=value,
            turn=state.iterations,
            tool_call_id=tc.id,
            tool_name=tc.name,
        )
        # add_citation is idempotent on citation_id(source, locator).
        stored = state.add_citation(citation)
        yield CitationEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            source=stored.source,
            locator=stored.locator,
            value=stored.value,
        )
        cite_result: dict[str, Any] = {
            "ok": True,
            "citation_id": citation_id(stored.source, stored.locator),
        }
        state.append_turn(
            Turn(role="tool", content=_content_for_history(cite_result), tool_call_id=tc.id)
        )
        yield ToolResultEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            call_id=tc.id,
            result=cite_result,
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
        clarify_result = {"ok": True, "awaiting_user_reply": True}
        state.append_turn(
            Turn(role="tool", content=_content_for_history(clarify_result), tool_call_id=tc.id)
        )
        yield ToolResultEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            call_id=tc.id,
            result=clarify_result,
            truncated=False,
            cached=False,
        )
        state.done = True
        return

    if tc.name == "stop":
        final = FinalAnswerEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            text=str(tc.args.get("reason", "")),
            metadata={"stop": True},
        )
        final = await plugins.on_final_answer(final, state)
        state.append_turn(Turn(role="assistant", content=final.text))
        yield final
        state.done = True
        return

    if tc.name == "escalate_to_oracle":
        # SPEC §5.5: arm a single-turn oracle swap; pick_adapter consumes the
        # flag at the top of the next iteration and reverts on the one after.
        from_model = state.adapter.model if state.adapter is not None else "unknown"
        to_model = state.oracle_adapter.model if state.oracle_adapter is not None else "(none)"
        try:
            oracle_arm(state)
            oracle_result: dict[str, Any] = {"ok": True, "armed_for_next_turn": True}
        except OracleNotConfigured as exc:
            oracle_result = {"error": str(exc)}
            to_model = "(unconfigured)"
        oracle_event = OracleEscalationEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            reason=str(tc.args.get("reason", "")),
            from_model=from_model,
            to_model=to_model,
        )
        await plugins.on_oracle_escalation(oracle_event, state)
        yield oracle_event
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

    # Unreachable: caller filtered on INTERCEPTED_TOOL_NAMES.
    raise AssertionError(f"unhandled intercepted tool: {tc.name}")


# ---------------------------------------------------------------------------
# Real tool execution
# ---------------------------------------------------------------------------
#
# Actual execution (G9 cache + G11 gather) lives in parallel.py. This wrapper
# owns event emission and history mutation so every special case stays in this
# file.


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
    plugins: PluginHost,
) -> AsyncIterator[Event]:
    """Emit ToolCall/ToolResult events for a batch of real tool calls.

    Order: every ``ToolCallEvent`` is emitted first (matching the order the
    model issued them), then results are emitted in the same order. When
    ``parallel`` is True the underlying calls are gathered concurrently but
    the event stream stays deterministic.

    Plugin hooks (SPEC §12) wrap each call: ``before_tool_call`` folds over the
    calls before dispatch (so a rewrite reaches the tool and the emitted
    ``ToolCallEvent``), and ``after_tool_call`` folds over each bounded result
    before it lands in history (so a redaction reaches the model's context).
    A transform-hook failure raises :class:`PluginHookError` for the caller.
    """
    # Fold every call through before_tool_call before any dispatch, so the
    # ToolCallEvent we emit reflects what actually runs.
    if plugins:
        calls = [await plugins.before_tool_call(tc, state) for tc in calls]

    for tc in calls:
        yield ToolCallEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            name=tc.name,
            args=tc.args,
            call_id=tc.id,
        )

    results = await execute_batch(
        calls,
        tools_by_name=tools_by_name,
        cache=cache,
        parallel=parallel,
    )

    for tc, outcome in zip(calls, results, strict=True):
        if outcome.errored:
            state.record_tool_error()
        else:
            state.record_tool_success()

        limit = resolve_limit(tc.name, char_limits, default_char_limit)
        truncated, was_truncated = truncate_for_tool(outcome.raw, limit)

        result_event = ToolResultEvent(
            seq=next_seq(),
            session_id=session_id,
            turn=state.iterations,
            call_id=tc.id,
            result=truncated,
            truncated=was_truncated,
            cached=outcome.cache_hit,
        )
        result_event = await plugins.after_tool_call(tc, result_event, state)

        # History uses the post-hook payload so a redaction stays out of context.
        state.append_turn(
            Turn(
                role="tool",
                content=_content_for_history(result_event.result),
                tool_call_id=tc.id,
            )
        )

        yield result_event


__all__ = [
    "PSEUDO_TOOL_NAMES",
    "RunnableTool",
    "run_loop",
]
