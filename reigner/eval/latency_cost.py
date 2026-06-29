"""``latency_cost`` eval check — token budget + wall-clock per case.

Surfaces what a case cost and fails it only when an explicit budget is blown.
The detail always reports total tokens and elapsed seconds (e.g.
``"8.1k tok · 1.2s"``); the optional ``max_tokens`` / ``max_seconds`` fields on
:class:`~reigner.eval.cases.EvalCase` turn that into a pass/fail gate.

Dollar cost (the scorecard's ``$`` column) is intentionally deferred:
``TokenUsage`` carries only token counts and ``CaseRun`` does not record the
model name, so a price can't be computed without a pricing table and extra
plumbing. Reporting tokens + wall-clock is honest; adding dollars later is
purely additive here.

Verdicts:

- ``pass`` — no budget set, or every set budget is satisfied. Detail carries the
  measured cost regardless.
- ``fail`` — a set ``max_tokens`` / ``max_seconds`` was exceeded; the detail
  names which.
"""

from __future__ import annotations

from reigner.eval.cases import EvalCase
from reigner.eval.checks import CaseRun, CheckResult, check


def _total_tokens(usage: dict[str, object]) -> int:
    """Total tokens from a ``TokenUsage`` dict, falling back to prompt+completion."""
    total = usage.get("total")
    if isinstance(total, int) and total > 0:
        return total
    prompt = usage.get("prompt")
    completion = usage.get("completion")
    return (prompt if isinstance(prompt, int) else 0) + (
        completion if isinstance(completion, int) else 0
    )


def _fmt_tokens(n: int) -> str:
    return f"{n / 1000:.1f}k tok" if n >= 1000 else f"{n} tok"


@check("latency_cost")
def latency_cost(case: EvalCase, run: CaseRun) -> CheckResult:
    """Report tokens + elapsed; fail only when a set budget is exceeded."""
    tokens = _total_tokens(run.usage)
    seconds = run.elapsed
    measured = f"{_fmt_tokens(tokens)} · {seconds:.1f}s"

    if case.max_tokens is not None and tokens > case.max_tokens:
        return CheckResult(
            "latency_cost", "fail", f"{tokens} tok exceeds max_tokens {case.max_tokens}"
        )
    if case.max_seconds is not None and seconds > case.max_seconds:
        return CheckResult(
            "latency_cost", "fail", f"{seconds:.1f}s exceeds max_seconds {case.max_seconds:g}"
        )
    return CheckResult("latency_cost", "pass", measured)


__all__ = ["latency_cost"]
