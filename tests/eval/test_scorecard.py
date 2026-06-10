"""Tests for render_scorecard — the SPEC §15.2 markdown output (T-28)."""

from __future__ import annotations

from reigner.eval.cases import EvalCase
from reigner.eval.checks import CaseRun, CheckResult
from reigner.eval.runner import CaseResult, SuiteResult, render_scorecard


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
