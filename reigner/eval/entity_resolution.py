"""``entity_resolution`` eval check — clarify vs guess (SPEC §15.1).

For an *ambiguous* query ("what was the company's revenue?" — which company?),
the right move is to ask, not to guess. This check makes that explicit: for a
case the author flagged as ambiguous (``expected_clarification: true``), it
passes only if the agent emitted a
:class:`~reigner.harness.events.ClarificationEvent` and fails if the agent
instead produced a final answer (i.e. guessed an entity).

It is deliberately scoped to *ambiguous* cases and returns ``na`` otherwise, so
it complements — rather than duplicates — the runner's always-on intrinsic
``expected_clarification`` check (which scores both directions for every case
that sets the flag).

Profile note (SPEC §6.3, see ``runner.py``): the ``"eval"`` profile strips
``request_clarification``, so a ``ClarificationEvent`` cannot fire under it —
evaluate ambiguous cases with ``profile="read_only"``.

Verdicts:

- ``na``   — ``expected_clarification`` is not ``True`` (case isn't ambiguous).
- ``pass`` — the agent clarified.
- ``fail`` — the agent answered directly (guessed) instead of clarifying.
"""

from __future__ import annotations

from reigner.eval.cases import EvalCase
from reigner.eval.checks import CaseRun, CheckResult, check
from reigner.harness.events import ClarificationEvent


@check("entity_resolution")
def entity_resolution(case: EvalCase, run: CaseRun) -> CheckResult:
    """Pass iff an ambiguous case was clarified rather than guessed."""
    if case.expected_clarification is not True:
        return CheckResult("entity_resolution", "na", "not an ambiguous case")

    clarified = any(isinstance(e, ClarificationEvent) for e in run.events)
    if clarified:
        return CheckResult("entity_resolution", "pass", "clarified")
    return CheckResult(
        "entity_resolution", "fail", "ambiguous query answered directly instead of clarifying"
    )


__all__ = ["entity_resolution"]
