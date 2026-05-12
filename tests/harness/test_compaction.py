"""Unit tests for harness.compaction (T-06, G5/G10)."""

from __future__ import annotations

from reigner.harness.compaction import compact_history, default_summariser, progressive
from reigner.harness.state import AgentState, Note, Turn


def _state(history: list[Turn] | None = None, **kw: object) -> AgentState:
    base: dict[str, object] = {
        "session_id": "s",
        "role": "r",
        "token_counter": lambda s: len(s),
        "context_budget_tokens": 1000,
    }
    base.update(kw)
    s = AgentState(**base)  # type: ignore[arg-type]
    if history:
        s.history = history
    return s


def _t(role: str, content: str) -> Turn:
    return Turn(role=role, content=content)


def test_compact_history_keeps_recent() -> None:
    s = _state(
        history=[
            _t("user", "u" * 200),
            _t("assistant", "a" * 200),
            _t("user", "recent-user"),
            _t("assistant", "recent-final"),
        ]
    )
    freed = compact_history(s, keep_recent=2)
    assert freed > 0
    assert len(s.history) == 3  # 1 summary + 2 recent
    assert s.history[0].content.startswith("[reigner:summary]")
    assert s.history[-1].content == "recent-final"


def test_compact_history_noop_when_short() -> None:
    s = _state(history=[_t("user", "u1"), _t("assistant", "a1")])
    assert compact_history(s, keep_recent=3) == 0
    assert len(s.history) == 2


def test_compact_preserves_notes() -> None:
    s = _state(history=[_t("user", "x" * 200), _t("assistant", "y" * 200), _t("user", "z" * 200)])
    s.notes = [Note(text="critical", turn=0)]
    compact_history(s, keep_recent=1)
    assert any(n.text == "critical" for n in s.notes)


def test_progressive_no_action_below_threshold() -> None:
    s = _state(context_budget_tokens=100_000)
    s.history = [_t("user", "hi")]
    outcome = progressive(s)
    assert outcome.level is None
    assert outcome.tokens_freed == 0


def test_progressive_tier_1_at_80pct() -> None:
    # 100 chars of history; budget=120 → pressure ~0.84 → tier 1.
    s = _state(
        history=[_t("user", "x" * 20) for _ in range(5)],
        context_budget_tokens=120,
        history_keep_recent=2,
    )
    outcome = progressive(s)
    assert outcome.level == 1
    assert len(s.history) == 3  # summary + 2 recent


def test_progressive_tier_3_at_95pct() -> None:
    s = _state(
        history=[_t("user", "x" * 100) for _ in range(10)],
        context_budget_tokens=200,  # ~5x over → way past 95%
        history_keep_recent=3,
    )
    outcome = progressive(s)
    assert outcome.level == 3
    # Tier 3 collapses to [summary, last_turn]; second compact_history call
    # with keep_recent=1 is a no-op since len == 2 already.
    assert len(s.history) <= 2


def test_default_summariser_counts_tools() -> None:
    turns = [
        Turn(role="assistant", content="", tool_calls=[{"name": "read", "id": "1", "args": {}}]),
        Turn(role="assistant", content="", tool_calls=[{"name": "read", "id": "2", "args": {}}]),
        Turn(role="assistant", content="", tool_calls=[{"name": "grep", "id": "3", "args": {}}]),
    ]
    summary = default_summariser(turns)
    assert "read:2" in summary
    assert "grep:1" in summary
