"""Eval framework — opinionated checks over a configured harness (SPEC §15).

Public surface:

- :class:`EvalCase` / :func:`load_cases` — declarative fixtures (``cases.py``).
- :class:`EvalSuite` — runs cases against a harness (``runner.py``).
- :class:`CaseResult` / :class:`SuiteResult` — structured results.
- :func:`render_scorecard` — the SPEC §15.2 markdown scorecard.
- :class:`CaseRun` / :class:`CheckResult` / :func:`check` / :func:`get_check` —
  the seam the T-29 checks register against (``checks.py``).
"""

from reigner.eval.cases import EvalCase, load_cases
from reigner.eval.checks import (
    CaseRun,
    CheckResult,
    CheckStatus,
    check,
    get_check,
    registered_checks,
)
from reigner.eval.runner import CaseResult, EvalSuite, SuiteResult, render_scorecard

__all__ = [
    "CaseResult",
    "CaseRun",
    "CheckResult",
    "CheckStatus",
    "EvalCase",
    "EvalSuite",
    "SuiteResult",
    "check",
    "get_check",
    "load_cases",
    "registered_checks",
    "render_scorecard",
]
