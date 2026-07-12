"""Per-session mutable state for the agent loop.

This module is the foundational data layer the loop reads and writes each
iteration. It deliberately stays minimal: data structures, prompt assembly,
context-pressure measurement, and the steering queue. Truncation, compaction,
nudges, and the tool-result cache live in `harness/{truncation,compaction,
nudges,cache}.py`; state exposes the data those modules mutate but does not
implement them itself.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, runtime_checkable

from reigner.tools.base import ToolSpec
from reigner.tools.provenance.citations import citation_id
from reigner.tools.provenance.lineage import Citation
from reigner.tools.registry import ToolRegistry
from reigner.types import Profile

TurnRole = Literal["user", "assistant", "tool"]
SteeringMode = Literal["interrupt", "queue"]


# ---------------------------------------------------------------------------
# Forward-dependency Protocol stub.
#
# `harness.adapters.base` provides the concrete ModelAdapter; we declare a
# minimal Protocol here so state.py stays self-contained and testable.
# ---------------------------------------------------------------------------


# ModelAdapter is owned by `harness.adapters.base`. We declare a stub
# here for typing — the concrete Protocol cannot be imported at module load
# because `adapters.base` imports `Prompt`/`ToolSpec` from this module. Users
# should import `ModelAdapter` from `reigner.harness.adapters` for runtime
# isinstance checks; the stub below is structurally compatible.
@runtime_checkable
class ModelAdapter(Protocol):
    """Adapter surface state needs at the type level. See `harness.adapters`."""

    name: str
    model: str


# ---------------------------------------------------------------------------
# History + scratchpad records
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(kw_only=True)
class Turn:
    """One message in the conversation as the model sees it.

    Adapters translate Turns to provider message formats. Events (events.py)
    are the wire format for UIs; Turns are the wire format for the model.
    """

    role: TurnRole
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None
    ts: datetime = field(default_factory=_utcnow)


@dataclass(kw_only=True)
class Note:
    """Scratchpad entry surfaced via `save_note` (G8).

    Notes survive history compaction so the model can rebuild context after
    older turns are summarised.
    """

    text: str
    turn: int
    ts: datetime = field(default_factory=_utcnow)


@dataclass(kw_only=True)
class Prompt:
    """Adapter-agnostic prompt produced by `build_prompt` (G1).

    Split intentionally so providers that support prompt caching can mark
    `stable` as cacheable. Adapters translate to provider-specific shapes.
    """

    stable: str
    """Role text + serialized tool schemas. Identical across iterations as
    long as the role and tool registry don't change — safe to cache."""

    dynamic_context: dict[str, Any]
    """Per-turn variables refreshed by `refresh_context` (G6/G7):
    `iters_remaining`, `now`, `answer_id`, plus any G7 injections."""

    messages: list[Turn]
    """Conversation history in order. Already compacted if compaction ran."""


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


_TIKTOKEN_ENCODER: Any = None


def _tiktoken_counter(text: str) -> int:
    """Default token counter using tiktoken's cl100k_base.

    Lazy-imported and cached so users who pass their own counter never pay the
    import cost. cl100k_base is OpenAI/Anthropic-shaped and good enough for
    pressure calculations; users who need exact counts for a specific provider
    can pass their own counter to AgentState.
    """
    global _TIKTOKEN_ENCODER
    if _TIKTOKEN_ENCODER is None:
        import tiktoken

        _TIKTOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
    return len(_TIKTOKEN_ENCODER.encode(text))


# ---------------------------------------------------------------------------
# AgentState
# ---------------------------------------------------------------------------


@dataclass(kw_only=True)
class AgentState:
    """Per-session container the loop reads and writes each iteration.

    Lifecycle: created when a Session starts, mutated by the loop and by
    user-facing APIs (`steer`, `save_note`), persisted via the session store.
    One AgentState per Session — never shared.
    """

    # --- identity / immutable-ish config --------------------------------
    session_id: str
    role: str
    """Composed REIGNER.md text + active skill blocks."""

    registry: ToolRegistry = field(default_factory=ToolRegistry)
    """Owning registry. Loop calls `registry.for_profile(profile)` per turn to
    derive the visible tool surface; `_stable_text` iterates the same view so
    the prompt's tool block matches what the model is told it can call."""

    profile: Profile = "full"
    """Filter applied to `registry` for this session's lifetime."""

    adapter: ModelAdapter | None = None
    oracle_adapter: ModelAdapter | None = None

    # --- budgets / thresholds -------------------------------------------
    max_iterations: int = 25
    context_budget_tokens: int = 100_000
    max_session_notes: int = 20
    history_keep_recent: int = 3
    nudge_interval: int = 3
    max_consecutive_errors: int = 3
    compaction_thresholds: tuple[float, float, float] = (0.80, 0.90, 0.95)

    # --- pluggable token counter ----------------------------------------
    token_counter: Callable[[str], int] = field(default=_tiktoken_counter)

    # --- mutable per-iteration ------------------------------------------
    history: list[Turn] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    pending_steering: list[tuple[str, SteeringMode]] = field(default_factory=list)
    iterations: int = 0
    done: bool = False
    dynamic_context: dict[str, Any] = field(default_factory=dict)
    _consecutive_errors: int = 0
    error_nudge_injected: bool = False
    """G4 latch: True once an error nudge has been appended for the current
    error streak. Cleared by ``record_tool_success``. Read by the loop to
    distinguish 'nudge and continue' from 'nudge already fired, now bail'."""

    oracle_armed: bool = False
    """True when ``escalate_to_oracle`` has been invoked and the next iteration
    should use ``oracle_adapter``. Cleared after one iteration so escalation is
    strictly single-turn."""

    # ------------------------------------------------------------------
    # History / scratchpad mutation
    # ------------------------------------------------------------------
    def append_turn(self, turn: Turn) -> None:
        """Append a turn to the conversation history."""
        self.history.append(turn)

    def add_note(self, text: str) -> Note:
        """Append a note, evicting the oldest if at cap (FIFO).

        FIFO instead of refusing the write so the model never has to handle
        "scratchpad full" errors mid-loop — older notes are presumed less
        relevant than what the model just decided to record.
        """
        note = Note(text=text, turn=self.iterations)
        self.notes.append(note)
        if len(self.notes) > self.max_session_notes:
            self.notes = self.notes[-self.max_session_notes :]
        return note

    def add_citation(self, citation: Citation) -> Citation:
        """Append a citation, idempotent on ``(source, locator, value)``.

        Citations are uncapped: a multi-fact answer may need many, and silent
        FIFO eviction would let early citations vanish — the faithfulness
        check would then flag those claims as hallucinations. Dedup is keyed
        on the full claim (source, locator, and value) so re-registering the
        *same* fact across turns collapses, while distinct facts that happen
        to share a locator both survive. The locator alone is not enough:
        prose sections are stored as a single blob, so every fact in a
        section resolves to the same ``source#locator`` (e.g. ``{line: 1}``);
        keying on the locator only would silently drop every fact after the
        first and the faithfulness check would flag them as hallucinations.
        Returns the existing citation on re-registration so callers see what's
        actually stored.
        """
        key = citation_id(citation.source, citation.locator)
        for existing in self.citations:
            if (
                citation_id(existing.source, existing.locator) == key
                and existing.value == citation.value
            ):
                return existing
        self.citations.append(citation)
        return citation

    # ------------------------------------------------------------------
    # Steering
    # ------------------------------------------------------------------
    def enqueue_steering(self, message: str, mode: SteeringMode = "interrupt") -> None:
        """Append a user steering message. Called by Session.steer.

        Mode is stored alongside the message; the loop decides whether to drop
        in-flight tool calls (`interrupt`) or let the iteration finish
        (`queue`) when it consumes the queue.
        """
        self.pending_steering.append((message, mode))

    def has_pending_steering(self) -> bool:
        """Return whether any steering messages are queued."""
        return bool(self.pending_steering)

    def consume_steering(self) -> list[tuple[str, SteeringMode]]:
        """Drain the steering queue and return the messages in FIFO order."""
        drained = list(self.pending_steering)
        self.pending_steering.clear()
        return drained

    # ------------------------------------------------------------------
    # Error tracking (G4 hook)
    # ------------------------------------------------------------------
    def record_tool_error(self) -> None:
        """Increment the consecutive-error counter (G4)."""
        self._consecutive_errors += 1

    def record_tool_success(self) -> None:
        """Reset the consecutive-error counter and clear the nudge latch."""
        self._consecutive_errors = 0
        self.error_nudge_injected = False

    def consecutive_errors(self) -> int:
        """Return the current consecutive-error count."""
        return self._consecutive_errors

    # ------------------------------------------------------------------
    # Dynamic context (G6 / G7)
    # ------------------------------------------------------------------
    def refresh_context(self) -> None:
        """Recompute per-turn variables. Called at the top of each iteration.

        G6 covers the deterministic fields (`iters_remaining`, `now`,
        `answer_id`). G7 ("surface relevant prior notes/citations") is left as
        a hook — a no-op in v0 — because relevance scoring is a bigger design
        question that doesn't need to land in the foundational state module.
        """
        self.dynamic_context = {
            "iters_remaining": max(0, self.max_iterations - self.iterations),
            "now": _utcnow().isoformat(),
            "answer_id": uuid.uuid4().hex,
        }
        self._inject_relevant_notes()

    def _inject_relevant_notes(self) -> None:
        """G7 placeholder. Real relevance lands with retrieval skills."""
        return None

    # ------------------------------------------------------------------
    # Token accounting
    # ------------------------------------------------------------------
    def tokens_used(self) -> int:
        """Approximate tokens currently in the prompt.

        Counts the stable preamble plus every turn's content. Approximate by
        design — the counter is pluggable and pressure thresholds (G10) only
        need ordering, not exactness.
        """
        total = self.token_counter(self._stable_text())
        for turn in self.history:
            total += self.token_counter(turn.content)
        return total

    def context_pressure(self) -> float:
        """Fraction of budget consumed. Drives G10 compaction tiers."""
        if self.context_budget_tokens <= 0:
            return 0.0
        return self.tokens_used() / self.context_budget_tokens

    # ------------------------------------------------------------------
    # Prompt assembly (G1)
    # ------------------------------------------------------------------
    def build_prompt(self) -> Prompt:
        """Assemble the prompt with a stable / dynamic boundary (G1).

        `stable` is byte-identical across iterations as long as `role` and the
        tool registry don't change — adapters that support prompt caching mark
        it cacheable. Dynamic state goes in `dynamic_context` and `messages`.
        """
        return Prompt(
            stable=self._stable_text(),
            dynamic_context=dict(self.dynamic_context),
            messages=list(self.history),
        )

    def _stable_text(self) -> str:
        """Role + serialized tool schemas. Stable across iterations.

        Pulls the filtered tool surface from the registry so the cached
        preamble matches what the model is told it can call this session.
        """
        tool_lines = [
            json.dumps(
                {
                    "name": t.name,
                    "description": t.description,
                    "readonly": t.readonly,
                    "schema": t.json_schema(),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            for t in self.registry.for_profile(self.profile)
        ]
        return self.role + "\n\n" + "\n".join(tool_lines) if tool_lines else self.role


__all__ = [
    "AgentState",
    "Citation",
    "ModelAdapter",
    "Note",
    "Prompt",
    "SteeringMode",
    "ToolSpec",
    "Turn",
    "TurnRole",
]
