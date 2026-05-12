"""History + progressive context compaction (G5, G10).

See SPEC.md §5.4 (G5, G10) and PRINCIPLES.md §3 (bounded outputs).

When ``state.context_pressure()`` crosses the configured thresholds (default
0.80 / 0.90 / 0.95) the loop calls :func:`progressive`, which decides whether
to compact and at which tier:

- **tier 1 (≥80%)**: compact history — keep the last ``history_keep_recent``
  turns verbatim; collapse older turns into a single synthetic summary turn.
- **tier 2 (≥90%)**: also shrink retained tool-result content to a one-line
  description per result, keeping the structural shape of the history.
- **tier 3 (≥95%)**: drop history to just the last turn plus the synthetic
  summary; notes (G8) always survive.

The discipline: compaction never touches ``state.notes`` (G8) — the scratchpad
is the explicit survival channel. Each compaction emits a ``CompactionEvent``
so UIs can render the level and tokens freed.

The default summariser is a deterministic structural digest (counts of tool
calls per name, retained message roles). An LLM-backed summariser is pluggable
via the ``summariser`` argument but out of scope for v0.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reigner.harness.state import AgentState, Turn


Summariser = Callable[[list["Turn"]], str]


@dataclass(frozen=True)
class CompactionOutcome:
    """Result of a single compaction call. ``None`` ``level`` means no-op."""

    level: int | None
    tokens_freed: int


def default_summariser(turns: list[Turn]) -> str:
    """Deterministic structural summary of ``turns``.

    Counts roles and tool-call frequencies. Cheap, no model call, sufficient
    for tests and for keeping older context navigable. Plugins can swap in an
    LLM summariser via the ``summariser`` argument.
    """
    role_counts: Counter[str] = Counter()
    tool_calls: Counter[str] = Counter()
    for t in turns:
        role_counts[t.role] += 1
        for tc in t.tool_calls or []:
            tool_calls[tc.get("name", "?")] += 1
    parts = [f"[reigner:summary] compacted {len(turns)} prior turn(s)"]
    if role_counts:
        parts.append("roles=" + ",".join(f"{r}:{n}" for r, n in sorted(role_counts.items())))
    if tool_calls:
        parts.append("tools=" + ",".join(f"{name}:{n}" for name, n in sorted(tool_calls.items())))
    return " | ".join(parts)


def compact_history(
    state: AgentState,
    *,
    keep_recent: int | None = None,
    summariser: Summariser = default_summariser,
) -> int:
    """G5: keep the last N turns verbatim; replace the rest with a summary.

    Returns the number of tokens freed (approximate, via the state token
    counter). A no-op when there are not enough older turns to summarise.
    Notes (G8) are untouched — they live on ``state.notes``.
    """
    from reigner.harness.state import Turn

    n_keep = state.history_keep_recent if keep_recent is None else keep_recent
    if len(state.history) <= n_keep:
        return 0

    older = state.history[:-n_keep] if n_keep > 0 else list(state.history)
    recent = state.history[-n_keep:] if n_keep > 0 else []

    before = sum(state.token_counter(t.content) for t in older)
    summary_turn = Turn(role="assistant", content=summariser(older))
    after = state.token_counter(summary_turn.content)

    state.history = [summary_turn, *recent]
    return max(0, before - after)


def _shrink_tool_results(state: AgentState) -> int:
    """Tier-2 helper: replace retained tool-result bodies with a one-line stub.

    Returns tokens freed. Tool-call records on assistant turns are kept as-is
    so the model still sees what it asked for; only the ``tool``-role
    responses are shrunk.
    """
    from reigner.harness.state import Turn

    freed = 0
    new_history: list[Turn] = []
    for turn in state.history:
        if turn.role != "tool":
            new_history.append(turn)
            continue
        body = turn.content
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict) and "_truncated" in parsed:
                # Already a truncation envelope; reuse its key info.
                keys = parsed.get("available_keys") or list(parsed.keys())[:5]
                stub = f"[reigner:compacted-result] keys={keys}"
            else:
                stub = f"[reigner:compacted-result] {type(parsed).__name__}"
        except (ValueError, TypeError):
            stub = "[reigner:compacted-result] (opaque)"
        freed += max(0, state.token_counter(body) - state.token_counter(stub))
        new_history.append(Turn(role="tool", content=stub, tool_call_id=turn.tool_call_id))
    state.history = new_history
    return freed


def _keep_only_last_turn(state: AgentState, summariser: Summariser) -> int:
    """Tier-3 helper: collapse to ``[summary, last_turn]``.

    The last turn is kept verbatim so the model sees its most recent step;
    everything else is rolled into the summary.
    """
    from reigner.harness.state import Turn

    if len(state.history) <= 1:
        return 0
    older = state.history[:-1]
    last = state.history[-1]
    before = sum(state.token_counter(t.content) for t in older)
    summary_turn = Turn(role="assistant", content=summariser(older))
    after = state.token_counter(summary_turn.content)
    state.history = [summary_turn, last]
    return max(0, before - after)


def progressive(
    state: AgentState,
    *,
    summariser: Summariser = default_summariser,
) -> CompactionOutcome:
    """G10: pick a compaction tier from current pressure and apply it.

    Returns the tier (1/2/3) and tokens freed. Tier 0 — pressure below the
    lowest threshold — returns ``(None, 0)`` and the loop emits no event.
    """
    t1, t2, t3 = state.compaction_thresholds
    pressure = state.context_pressure()

    if pressure < t1:
        return CompactionOutcome(level=None, tokens_freed=0)

    if pressure >= t3:
        freed = _keep_only_last_turn(state, summariser)
        # Also collapse older entries the summary may have left behind.
        freed += compact_history(state, keep_recent=1, summariser=summariser)
        return CompactionOutcome(level=3, tokens_freed=freed)

    if pressure >= t2:
        freed = compact_history(state, summariser=summariser)
        freed += _shrink_tool_results(state)
        return CompactionOutcome(level=2, tokens_freed=freed)

    return CompactionOutcome(level=1, tokens_freed=compact_history(state, summariser=summariser))


__all__ = [
    "CompactionOutcome",
    "Summariser",
    "compact_history",
    "default_summariser",
    "progressive",
]
