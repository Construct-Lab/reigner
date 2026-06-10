"""Eval suite runner — runs cases against a harness and scores them (SPEC §15).

``EvalSuite.run(harness, checks=[...])`` runs each :class:`~reigner.eval.cases.EvalCase`
through the harness and produces a :class:`SuiteResult`. Evaluation has two tiers:

1. **Intrinsic** — always evaluated, no T-29 dependency. The cheap declarative
   assertions a case carries directly: ``forbidden_phrases`` (substring scan of
   the final answer) and ``expected_clarification`` (did a ``ClarificationEvent``
   fire?). Each emits a :class:`~reigner.eval.checks.CheckResult`.
2. **Named** — the analyzers listed in ``checks=[...]``, resolved from the
   :func:`~reigner.eval.checks.check` registry. These are T-29's five
   (``faithfulness`` etc.); this module only runs them.

Run mechanics:

- Each case gets a **fresh** ``harness.session(profile=...)`` (default
  ``"eval"``), so there is no cross-case cache/history leak.
- Cases run **sequentially** — determinism and predictable token cost are the
  point of the eval profile, and cases are independent so concurrency is a
  trivial later add.
- The suite **never aborts**: if a case raises or ends without a final answer,
  the failure is captured into its :class:`~reigner.eval.checks.CaseRun`
  (``final=None``) and the remaining cases still run.

Profile note: the named ``"eval"`` profile (SPEC §6.3) strips
``request_clarification`` for determinism, so an ``expected_clarification: true``
case cannot pass under it. Evaluate clarification behavior with
``profile="read_only"`` until the registry reconciles eval-vs-clarification.
"""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from reigner.eval.cases import EvalCase, load_cases
from reigner.eval.checks import CaseRun, CheckFn, CheckResult, get_check
from reigner.harness.events import ClarificationEvent, ErrorEvent, FinalAnswerEvent
from reigner.tools.registry import Profile

if TYPE_CHECKING:
    from reigner.harness.agent import Harness


@dataclass
class CaseResult:
    """A case's run plus every check's verdict on it."""

    case: EvalCase
    run: CaseRun
    results: list[CheckResult]

    @property
    def passed(self) -> bool:
        """True unless some check returned ``fail`` (``na`` and ``pass`` are OK)."""
        return all(r.status != "fail" for r in self.results)


@dataclass
class SuiteResult:
    """The outcome of running every case in a suite."""

    cases: list[CaseResult]

    @property
    def passed(self) -> bool:
        """True iff every case passed."""
        return all(c.passed for c in self.cases)

    @property
    def n_passed(self) -> int:
        return sum(1 for c in self.cases if c.passed)

    @property
    def n_failed(self) -> int:
        return sum(1 for c in self.cases if not c.passed)


class EvalSuite:
    """A collection of :class:`EvalCase` runnable against a harness."""

    def __init__(self, cases: list[EvalCase]) -> None:
        self.cases = list(cases)

    @classmethod
    def from_yaml(cls, path: str | Path) -> EvalSuite:
        """Load a suite from a ``cases.yaml`` file (SPEC §15, init scaffold)."""
        return cls(load_cases(path))

    async def run(
        self,
        harness: Harness,
        checks: list[str] | None = None,
        *,
        profile: Profile = "eval",
    ) -> SuiteResult:
        """Run every case through ``harness`` and score it.

        ``checks`` names the registered analyzers (T-29) to run on top of the
        always-on intrinsic assertions. Unknown names raise ``KeyError`` *before*
        any case runs, so a typo never costs a model call.
        """
        # Resolve up front: fail fast on a bad name before spending model calls.
        resolved = [get_check(name) for name in (checks or [])]
        results = [await self._run_case(harness, case, resolved, profile) for case in self.cases]
        return SuiteResult(cases=results)

    async def _run_case(
        self,
        harness: Harness,
        case: EvalCase,
        resolved: list[CheckFn],
        profile: Profile,
    ) -> CaseResult:
        session = harness.session(profile=profile)
        final: FinalAnswerEvent | None = None
        events = []
        start = time.perf_counter()
        try:
            async for event in session.run_stream(case.query):
                events.append(event)
                if isinstance(event, FinalAnswerEvent):
                    final = event
        except Exception as exc:  # noqa: BLE001 — one bad case must not sink the suite
            events.append(
                ErrorEvent(
                    seq=len(events),
                    session_id=session.id,
                    turn=0,
                    error=f"{type(exc).__name__}: {exc}",
                    recoverable=False,
                )
            )
        elapsed = time.perf_counter() - start

        usage: dict[str, Any] = {}
        if final is not None and isinstance(final.metadata, dict):
            reported = final.metadata.get("usage")
            if isinstance(reported, dict):
                usage = reported

        run = CaseRun(
            final=final,
            events=events,
            citations=list(session.citations()),
            elapsed=elapsed,
            usage=usage,
        )

        results = _intrinsic_checks(case, run)
        for fn in resolved:
            out = fn(case, run)
            if inspect.isawaitable(out):
                out = await out
            results.append(out)
        return CaseResult(case=case, run=run, results=results)


# ---------------------------------------------------------------------------
# Intrinsic tier — always evaluated, no T-29 dependency.
# ---------------------------------------------------------------------------


def _intrinsic_checks(case: EvalCase, run: CaseRun) -> list[CheckResult]:
    results: list[CheckResult] = []
    if case.forbidden_phrases:
        results.append(_forbidden_phrases(case, run))
    if case.expected_clarification is not None:
        results.append(_expected_clarification(case, run))
    return results


def _forbidden_phrases(case: EvalCase, run: CaseRun) -> CheckResult:
    if run.final is None:
        return CheckResult("forbidden_phrases", "na", "no final answer to scan")
    text = run.answer_text.lower()
    hits = [p for p in case.forbidden_phrases if p.lower() in text]
    if hits:
        joined = ", ".join(repr(h) for h in hits)
        return CheckResult("forbidden_phrases", "fail", f"answer contains {joined}")
    return CheckResult("forbidden_phrases", "pass")


def _expected_clarification(case: EvalCase, run: CaseRun) -> CheckResult:
    clarified = any(isinstance(e, ClarificationEvent) for e in run.events)
    expected = case.expected_clarification
    if clarified == expected:
        return CheckResult("expected_clarification", "pass", "clarified" if clarified else "")
    if expected:
        return CheckResult(
            "expected_clarification", "fail", "expected a clarification; agent answered directly"
        )
    return CheckResult(
        "expected_clarification", "fail", "agent clarified; a direct answer was expected"
    )


# ---------------------------------------------------------------------------
# Scorecard — SPEC §15.2 markdown table. Co-located so it's testable without
# the CLI (T-21); T-21 just calls render_scorecard on the SuiteResult.
# ---------------------------------------------------------------------------


def render_scorecard(result: SuiteResult, *, date: str | None = None) -> str:
    """Render a :class:`SuiteResult` as the SPEC §15.2 markdown scorecard."""
    day = date or datetime.now(UTC).date().isoformat()
    lines = [f"## Eval results — {day}", ""]

    # Columns in first-seen order across cases (intrinsic before named, since
    # every case evaluates the same checks in the same order).
    columns: list[str] = []
    for case_result in result.cases:
        for check_result in case_result.results:
            if check_result.name not in columns:
                columns.append(check_result.name)

    if columns:
        lines.append("| Case | " + " | ".join(columns) + " |")
        lines.append("|---|" + "---|" * len(columns))
    else:
        lines.append("| Case |")
        lines.append("|---|")

    for case_result in result.cases:
        by_name = {r.name: r for r in case_result.results}
        cells = [case_result.case.id]
        cells.extend(_cell(by_name[col]) if col in by_name else "—" for col in columns)
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    lines.append(f"{len(result.cases)} cases · {result.n_passed} passed · {result.n_failed} failed")
    for case_result in result.cases:
        for check_result in case_result.results:
            if check_result.status == "fail":
                suffix = f" — {check_result.detail}" if check_result.detail else ""
                lines.append(f"✗ {case_result.case.id} · {check_result.name}{suffix}")
    return "\n".join(lines)


def _cell(result: CheckResult) -> str:
    if result.status == "pass":
        return "✓" + (f" ({result.detail})" if result.detail else "")
    if result.status == "na":
        return "n/a"
    return "✗" + (f" — {result.detail}" if result.detail else "")


__all__ = [
    "CaseResult",
    "EvalSuite",
    "SuiteResult",
    "render_scorecard",
]
