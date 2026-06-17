"""Tests for render_scorecard / render_report — markdown output (T-28, T-29)."""

from __future__ import annotations

from reigner.eval.cases import EvalCase
from reigner.eval.checks import CaseRun, CheckResult
from reigner.eval.runner import CaseResult, SuiteResult, render_report, render_scorecard
from reigner.harness.events import CitationEvent, FinalAnswerEvent, ToolCallEvent
from reigner.tools.provenance.lineage import Citation


def _run() -> CaseRun:
    return CaseRun(final=None, events=[], citations=[], elapsed=0.0)


def _suite() -> SuiteResult:
    return SuiteResult(
        cases=[
            CaseResult(
                case=EvalCase(id="apple_rnd_2024", query="q"),
                run=_run(),
                results=[
                    CheckResult("faithfulness", "pass"),
                    CheckResult("coverage", "pass"),
                ],
            ),
            CaseResult(
                case=EvalCase(id="ambiguous_revenue", query="q"),
                run=_run(),
                results=[
                    CheckResult("faithfulness", "na"),
                    CheckResult("coverage", "na"),
                    CheckResult("expected_clarification", "pass", "clarified"),
                ],
            ),
            CaseResult(
                case=EvalCase(id="msft_buyback_2023", query="q"),
                run=_run(),
                results=[
                    CheckResult("faithfulness", "fail", 'claim "$67B" not cited'),
                    CheckResult("coverage", "pass"),
                ],
            ),
        ]
    )


def test_scorecard_structure() -> None:
    md = render_scorecard(_suite(), date="2026-06-09")
    lines = md.splitlines()
    assert lines[0] == "## Eval results — 2026-06-09"
    # Columns are first-seen across cases: faithfulness, coverage, then the
    # clarification column introduced by the second case.
    assert lines[2] == "| Case | faithfulness | coverage | expected_clarification |"
    assert lines[3] == "|---|---|---|---|"


def test_scorecard_cell_rendering() -> None:
    md = render_scorecard(_suite(), date="2026-06-09")
    assert "| apple_rnd_2024 | ✓ | ✓ | — |" in md
    assert "| ambiguous_revenue | n/a | n/a | ✓ (clarified) |" in md
    assert '| msft_buyback_2023 | ✗ — claim "$67B" not cited | ✓ | — |' in md


def test_scorecard_summary_and_failures() -> None:
    md = render_scorecard(_suite(), date="2026-06-09")
    assert "3 cases · 2 passed · 1 failed" in md
    assert '✗ msft_buyback_2023 · faithfulness — claim "$67B" not cited' in md


def test_scorecard_empty_suite() -> None:
    md = render_scorecard(SuiteResult(cases=[]), date="2026-06-09")
    assert "0 cases · 0 passed · 0 failed" in md


def _report_suite() -> SuiteResult:
    answered = CaseRun(
        final=FinalAnswerEvent(
            seq=3, session_id="s", turn=0, text="Amity has 449 faculty.", metadata={}
        ),
        events=[
            ToolCallEvent(
                seq=0,
                session_id="s",
                turn=0,
                name="get_json_field",
                args={"path": "IR-E-U-0497/2024/metrics.json", "fields": ["faculty_count"]},
                call_id="c0",
            ),
            CitationEvent(
                seq=1,
                session_id="s",
                turn=0,
                source="IR-E-U-0497/2024/metrics.json",
                locator={"field": "faculty_count"},
                value=449,
            ),
        ],
        citations=[
            Citation(
                source="IR-E-U-0497/2024/metrics.json",
                locator={"field": "faculty_count"},
                value=449,
                turn=0,
            )
        ],
        elapsed=1.2,
        usage={"total": 5100},
    )
    return SuiteResult(
        cases=[
            CaseResult(
                case=EvalCase(id="amity_faculty", query="How many faculty at Amity?"),
                run=answered,
                results=[CheckResult("faithfulness", "pass"), CheckResult("coverage", "pass")],
            )
        ]
    )


def test_report_includes_scorecard_query_response_and_trace() -> None:
    md = render_report(_report_suite(), date="2026-06-09")
    assert "# Eval report" in md
    assert "## Eval results — 2026-06-09" in md  # scorecard embedded
    assert "## Per-case detail" in md
    assert "### amity_faculty — PASSED" in md
    assert "- **Query:** How many faculty at Amity?" in md
    assert "- **Response:** Amity has 449 faculty." in md
    assert "→ `get_json_field(" in md  # trace
    assert "`IR-E-U-0497/2024/metrics.json#field=faculty_count` = 449" in md  # citation
    assert "✓ `faithfulness`" in md  # check verdict
    assert "5100 tokens · 1.2s" in md


def test_report_marks_clarified_case() -> None:
    run = CaseRun(final=None, events=[], citations=[], elapsed=0.4)
    suite = SuiteResult(
        cases=[
            CaseResult(
                case=EvalCase(id="ambig", query="which one?"),
                run=run,
                results=[CheckResult("faithfulness", "na", "no numeric claims")],
            )
        ]
    )
    md = render_report(suite, date="2026-06-09")
    assert "- **Response:** _(no final answer)_" in md
    assert "_(no tool calls)_" in md
    assert "- **Citations:**\n    - _(none)_" in md
