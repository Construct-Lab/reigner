"""Tests for the collapsing TurnRenderer.

Renders to a non-terminal Console (so the live region is skipped and finish()
commits plainly), then asserts on the committed transcript: the collapsed
retrieval summary, the pulled-out Sources block, and the answer panel.
"""

from __future__ import annotations

import io

from rich.console import Console

from reigner.cli._render import TurnRenderer
from reigner.harness.events import (
    CitationEvent,
    FinalAnswerEvent,
    ToolCallEvent,
    ToolResultEvent,
)

_ENV = {"seq": 0, "session_id": "s", "turn": 0}


def _call(call_id: str, name: str, **args: object) -> ToolCallEvent:
    return ToolCallEvent(**_ENV, name=name, args=dict(args), call_id=call_id)


def _result(call_id: str, result: object, *, truncated: bool = False) -> ToolResultEvent:
    return ToolResultEvent(
        **_ENV, call_id=call_id, result=result, truncated=truncated, cached=False
    )


def _render(events: list[object], *, verbose: bool = False, model_id: str | None = None) -> str:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=100)
    renderer = TurnRenderer(console, verbose=verbose, model_id=model_id)
    with renderer.live():
        for ev in events:
            renderer.feed(ev)
    renderer.finish()
    return buf.getvalue()


def test_collapsed_summary_counts_calls_and_truncations() -> None:
    out = _render(
        [
            _call("c1", "bm25_search", query="supremacy"),
            _result("c1", {"hits": [1, 2, 3]}),
            _call("c2", "grep_artifact", pattern="Rule of Law"),
            _result("c2", {"matches": [1], "available_keys": ["matches"]}, truncated=True),
            FinalAnswerEvent(**_ENV, text="the answer", metadata={}),
        ]
    )
    assert "Retrieved" in out
    assert "2 calls" in out
    assert "1 truncated" in out
    assert "the answer" in out


def _run_with_usage(usage: dict[str, int], *, model_id: str | None) -> str:
    return _render(
        [
            _call("c1", "bm25_search", query="supremacy"),
            _result("c1", {"hits": [1]}),
            FinalAnswerEvent(**_ENV, text="a", metadata={"usage": usage}),
        ],
        model_id=model_id,
    )


def test_recap_shows_cost_for_known_model() -> None:
    # 1M fresh input on Opus 4.8 ($5/1M) → $5.000, plus the token count.
    out = _run_with_usage(
        {"prompt": 1_000_000, "completion": 0, "total": 1_000_000}, model_id="claude-opus-4-8"
    )
    assert "$5.000" in out
    assert "1000.0k tok" in out


def test_recap_omits_cost_for_unknown_model() -> None:
    out = _run_with_usage(
        {"prompt": 1_000_000, "completion": 0, "total": 1_000_000}, model_id="mystery-model"
    )
    assert "$" not in out
    assert "1000.0k tok" in out  # tokens still shown


def test_recap_omits_cost_without_a_model_id() -> None:
    out = _run_with_usage({"prompt": 1_000_000, "completion": 0, "total": 1_000_000}, model_id=None)
    assert "$" not in out


def test_citations_pulled_into_numbered_sources_block() -> None:
    out = _render(
        [
            _call("c1", "bm25_search", query="x"),
            _result("c1", {"hits": [1]}),
            # register_citation emits a call + result too, but is represented
            # only via the CitationEvent / Sources block.
            _call("c2", "register_citation", source="foundations/rule_of_law"),
            CitationEvent(
                **_ENV,
                source="foundations/rule_of_law",
                locator={"para": 1},
                value="text",
            ),
            _result("c2", {"ok": True}),
            CitationEvent(
                **_ENV,
                source="foundations/rule_of_law",
                locator={"para": 2},
                value="text",
            ),
            FinalAnswerEvent(**_ENV, text="answer", metadata={}),
        ]
    )
    assert "Sources" in out
    assert "[1]" in out and "[2]" in out
    assert "para=1" in out
    # register_citation is not counted as a retrieval call.
    assert "1 call" in out


def test_no_retrieval_no_final_stays_silent() -> None:
    out = _render([])
    assert out.strip() == ""


def test_answer_only_turn_renders_panel_without_summary() -> None:
    out = _render([FinalAnswerEvent(**_ENV, text="just answer", metadata={})])
    assert "just answer" in out
    assert "Retrieved" not in out


def test_collapsed_hides_per_call_detail_but_keeps_recap() -> None:
    events = [
        _call("c1", "bm25_search", query="widgets"),
        _result("c1", {"hits": [1, 2]}),
        FinalAnswerEvent(**_ENV, text="a", metadata={}),
    ]
    out = _render(events, verbose=False)
    # The recap stands in; the per-call line (its args) is folded away.
    assert "Retrieved" in out
    assert "1 call" in out
    assert "widgets" not in out
    assert "/expand" in out


def test_verbose_streams_per_call_detail() -> None:
    events = [
        _call("c1", "bm25_search", query="widgets"),
        _result("c1", {"hits": [1, 2]}),
        FinalAnswerEvent(**_ENV, text="a", metadata={}),
    ]
    out = _render(events, verbose=True)
    assert "widgets" in out
    assert "2 hits" in out
    # No expand hint in verbose mode — the detail is already shown.
    assert "/expand" not in out


def test_print_detail_reprints_calls_on_demand() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=100)
    r = TurnRenderer(console, verbose=False)
    with r.live():
        r.feed(_call("c1", "bm25_search", query="widgets"))
        r.feed(_result("c1", {"hits": [1, 2]}))
        r.feed(FinalAnswerEvent(**_ENV, text="a", metadata={}))
    r.finish()
    assert "widgets" not in buf.getvalue()  # collapsed

    assert r.print_detail() is True
    assert "widgets" in buf.getvalue()  # expanded on demand


def test_print_detail_false_when_no_retrieval() -> None:
    buf = io.StringIO()
    r = TurnRenderer(Console(file=buf, force_terminal=False, width=100))
    assert r.print_detail() is False
