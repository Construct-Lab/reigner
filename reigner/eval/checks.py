"""Eval check contract and registry — the seam concrete checks plug into.

This module owns the *shape* of a check and how a check is discovered by name;
it deliberately ships **no concrete checks**. The five analyzers
(``faithfulness``, ``repeated_calls``, ``entity_resolution``, ``coverage``,
``latency_cost``) live in their own modules and register themselves here via
the :func:`check` decorator, so they land with zero edits to the runner.

The three pieces:

- :class:`CaseRun` — everything the runner captures from one harness run of a
  case: the terminal answer (or ``None`` if the agent clarified / errored / made
  no progress), the full event stream, the registered citations, wall-clock
  elapsed, and the token ``usage`` dict. Every check reads from this — no check
  needs the live loop, because every check is computable from a completed run
  record.
- :class:`CheckResult` — a ternary verdict (``pass`` / ``fail`` / ``na``) plus a
  human-readable ``detail``. ``na`` lets a check declare itself inapplicable
  (e.g. ``coverage`` on a case the agent clarified) instead of faking a verdict;
  the scorecard shows exactly these three states.
- :func:`check` / :func:`get_check` — a module-level name→function registry. A
  check is any callable ``(EvalCase, CaseRun) -> CheckResult`` (or its awaitable
  form, so a check may call a model). The runner resolves the names passed to
  ``suite.run(..., checks=[...])`` against this registry.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from reigner.eval.cases import EvalCase
    from reigner.harness.events import Event, FinalAnswerEvent
    from reigner.tools.provenance.lineage import Citation

CheckStatus = Literal["pass", "fail", "na"]


@dataclass(frozen=True)
class CaseRun:
    """A completed harness run of one :class:`~reigner.eval.cases.EvalCase`.

    Everything a check needs, captured by the runner. ``final`` is ``None`` when
    the agent did not produce a final answer for the round — it clarified, hit
    an unrecoverable error, or made no progress; checks interpret that state
    (often as ``fail`` or ``na``) rather than the suite treating it as a crash.
    """

    final: FinalAnswerEvent | None
    events: list[Event]
    citations: list[Citation]
    elapsed: float
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def answered(self) -> bool:
        """True iff the run produced a final answer."""
        return self.final is not None

    @property
    def answer_text(self) -> str:
        """The final answer text, or ``""`` if there was no final answer."""
        return self.final.text if self.final is not None else ""


@dataclass(frozen=True)
class CheckResult:
    """One check's verdict on one case.

    ``status`` is ternary: ``pass``/``fail``/``na``. ``detail`` is a
    short human-readable note — the reason for a failure, or context for a pass
    (e.g. ``"clarified"``). The runner renders it inline in the scorecard.
    """

    name: str
    status: CheckStatus
    detail: str = ""


# A check is a callable over (case, run). It may be sync or async — async lets a
# check call a model (e.g. an LLM-judged faithfulness check); the runner awaits
# the result when it is awaitable.
CheckFn = Callable[["EvalCase", "CaseRun"], "CheckResult | Awaitable[CheckResult]"]

_REGISTRY: dict[str, CheckFn] = {}


def check(name: str) -> Callable[[CheckFn], CheckFn]:
    """Register a check function under ``name``.

    Used by each analyzer module::

        @check("faithfulness")
        async def faithfulness(case: EvalCase, run: CaseRun) -> CheckResult:
            ...

    Returns the function unchanged so it stays directly callable in tests.
    Raises ``ValueError`` on a duplicate name so two checks can't silently
    shadow each other.
    """

    def register(fn: CheckFn) -> CheckFn:
        if name in _REGISTRY:
            raise ValueError(f"duplicate eval check name: {name!r}")
        _REGISTRY[name] = fn
        return fn

    return register


def get_check(name: str) -> CheckFn:
    """Resolve a registered check by name, or raise a helpful ``KeyError``.

    The error lists every registered name so a typo (or a missing check-module
    import) is obvious at the call site.
    """
    try:
        return _REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise KeyError(f"unknown eval check {name!r}; registered: {available}") from None


def registered_checks() -> list[str]:
    """Names of every currently registered check, sorted."""
    return sorted(_REGISTRY)


__all__ = [
    "CaseRun",
    "CheckFn",
    "CheckResult",
    "CheckStatus",
    "check",
    "get_check",
    "registered_checks",
]
