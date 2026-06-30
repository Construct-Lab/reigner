"""``repeated_calls`` eval check — redundant / looping tool calls.

A retrieval agent that re-issues the *same* tool call is either stuck in a loop
or wasting budget re-fetching what it already has. This check flags that: it
builds an identity key ``(name, canonicalized args)`` for every
:class:`~reigner.harness.events.ToolCallEvent` in the run and fails the case if
any key occurs two or more times.

Deterministic — it reads only ``run.events``. Verdicts:

- ``na``  — the run made no tool calls (nothing to judge).
- ``pass`` — every tool call is unique.
- ``fail`` — at least one identical call repeated; the detail names the worst
  offender and its count.

Args are canonicalized with :func:`~reigner.tools.provenance.citations.canonicalize_locator`
(the same sorted-key rendering used for citation dedup), so two calls with the
same arguments in a different key order count as identical.
"""

from __future__ import annotations

from collections import Counter

from reigner.eval.cases import EvalCase
from reigner.eval.checks import CaseRun, CheckResult, check
from reigner.harness.events import ToolCallEvent
from reigner.tools.provenance.citations import canonicalize_locator


@check("repeated_calls")
def repeated_calls(case: EvalCase, run: CaseRun) -> CheckResult:
    """Fail if any ``(name, args)`` tool call repeats; ``na`` if none were made."""
    counts: Counter[tuple[str, str]] = Counter(
        (e.name, canonicalize_locator(e.args)) for e in run.events if isinstance(e, ToolCallEvent)
    )
    if not counts:
        return CheckResult("repeated_calls", "na", "no tool calls")

    (name, _args), worst = counts.most_common(1)[0]
    if worst >= 2:
        return CheckResult(
            "repeated_calls", "fail", f"{name!r} called {worst}× with identical args"
        )
    return CheckResult("repeated_calls", "pass")


__all__ = ["repeated_calls"]
