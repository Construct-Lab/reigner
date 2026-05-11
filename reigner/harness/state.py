"""Per-session mutable state for the agent loop.

See SPEC.md §5.1 (Session vs Harness split), §5.3 (the loop), §5.4 (G1, G6, G7),
§5.6 (steering), and issue #3.

This module is the foundational data layer the loop reads and writes each
iteration. It deliberately stays minimal: data structures, prompt assembly,
context-pressure measurement, and the steering queue. Truncation, compaction,
nudges, and the tool-result cache live in T-06 (`harness/{truncation,compaction,
nudges,cache}.py`); state exposes the data those modules will mutate but does
not implement them itself.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, runtime_checkable

TurnRole = Literal["user", "assistant", "tool"]
SteeringMode = Literal["interrupt", "queue"]


# ---------------------------------------------------------------------------
# Forward-dependency Protocol stubs.
#
# T-04 (`harness/adapters/`) provides concrete ModelAdapter implementations and
# T-07 (`tools/base.py`) provides the real ToolSpec. We declare minimal shapes
# here so state.py is self-contained and testable without those modules.
# ---------------------------------------------------------------------------


@runtime_checkable
class ToolSpec(Protocol):
    """Minimum surface state needs from a tool. T-07 will own the full type."""

    name: str
    description: str
    readonly: bool

    def json_schema(self) -> dict[str, Any]: ...


# ModelAdapter is owned by `harness.adapters.base` (T-04). We declare a stub
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
    `stable` as cacheable. T-04 adapters translate to provider-specific shapes.
    """

    stable: str
    """Role text + serialized tool schemas. Identical across iterations as
    long as the role and tool registry don't change — safe to cache."""

    dynamic_context: dict[str, Any]
    """Per-turn variables refreshed by `refresh_context` (G6/G7):
    `iters_remaining`, `now`, `answer_id`, plus any G7 injections."""

    messages: list[Turn]
    """Conversation history in order. Already compacted if T-06 ran."""


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
    user-facing APIs (`steer`, `save_note`), persisted via the session store
    (T-24). One AgentState per Session — never shared.
    """

    # --- identity / immutable-ish config --------------------------------
    session_id: str
    role: str
    """Composed REIGNER.md text + active skill blocks. T-30/T-31 produce it."""

    tools: list[ToolSpec] = field(default_factory=list)
    adapter: ModelAdapter | None = None
    oracle_adapter: ModelAdapter | None = None

    # --- budgets / thresholds (defaults track SPEC §13) -----------------
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
    pending_steering: list[tuple[str, SteeringMode]] = field(default_factory=list)
    iterations: int = 0
    done: bool = False
    dynamic_context: dict[str, Any] = field(default_factory=dict)
    _consecutive_errors: int = 0

    # ------------------------------------------------------------------
    # History / scratchpad mutation
    # ------------------------------------------------------------------
    def append_turn(self, turn: Turn) -> None:
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

    # ------------------------------------------------------------------
    # Steering (§5.6)
    # ------------------------------------------------------------------
    def enqueue_steering(self, message: str, mode: SteeringMode = "interrupt") -> None:
        """Append a user steering message. Called by Session.steer.

        Mode is stored alongside the message; the loop (T-05) decides whether
        to drop in-flight tool calls (`interrupt`) or let the iteration finish
        (`queue`) when it consumes the queue.
        """
        self.pending_steering.append((message, mode))

    def has_pending_steering(self) -> bool:
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
        self._consecutive_errors += 1

    def record_tool_success(self) -> None:
        self._consecutive_errors = 0

    def consecutive_errors(self) -> int:
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
        """Role + serialized tool schemas. Stable across iterations."""
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
            for t in self.tools
        ]
        return self.role + "\n\n" + "\n".join(tool_lines) if tool_lines else self.role


__all__ = [
    "AgentState",
    "ModelAdapter",
    "Note",
    "Prompt",
    "SteeringMode",
    "ToolSpec",
    "Turn",
    "TurnRole",
]
