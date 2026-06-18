"""Eval cases — the declarative fixtures a suite runs (SPEC §15).

An :class:`EvalCase` is one query plus expectations about the agent's answer.
The fields mirror the ``eval/cases.yaml`` scaffold produced by ``reigner init``:

    cases:
      - id: apple_rnd_2024
        query: "What were Apple's R&D expenses in 2024?"
        expected_citations:
          - "AAPL/2024/metrics.json#field=research_and_development"
        forbidden_phrases: ["I think", "approximately"]
        expected_clarification: false

``expected_clarification`` is tri-state: ``None`` (the default, and the meaning
of an omitted key) asserts nothing, so a case that never opted in does not get a
spurious "should not have clarified" row. ``expected_citations`` is carried
through untouched — matching it against registered citations is the
``coverage``/``faithfulness`` checks' job, not the case's.

``max_tokens`` / ``max_seconds`` are optional per-case budgets the
``latency_cost`` check gates on; omitted (``None``) means report-only, no gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_KNOWN_FIELDS = frozenset(
    {
        "id",
        "query",
        "expected_citations",
        "forbidden_phrases",
        "expected_clarification",
        "max_tokens",
        "max_seconds",
    }
)


@dataclass
class EvalCase:
    """One eval fixture: a query and what a correct run should look like."""

    id: str
    query: str
    expected_citations: list[str] = field(default_factory=list)
    forbidden_phrases: list[str] = field(default_factory=list)
    expected_clarification: bool | None = None
    max_tokens: int | None = None
    max_seconds: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalCase:
        """Build a case from one YAML/JSON mapping, validating its shape.

        Raises ``ValueError`` on a missing ``id``/``query``, an unknown key
        (catches typos like ``forbidden_phrase``), a non-bool
        ``expected_clarification``, or a non-positive ``max_tokens``/
        ``max_seconds`` budget.
        """
        if not isinstance(data, dict):
            raise ValueError(f"eval case must be a mapping, got {type(data).__name__}")

        unknown = set(data) - _KNOWN_FIELDS
        if unknown:
            allowed = ", ".join(sorted(_KNOWN_FIELDS))
            raise ValueError(
                f"eval case has unknown field(s): {', '.join(sorted(unknown))}. Allowed: {allowed}."
            )

        if "id" not in data or "query" not in data:
            missing = ", ".join(k for k in ("id", "query") if k not in data)
            raise ValueError(f"eval case missing required field(s): {missing}")

        clarification = data.get("expected_clarification")
        if clarification is not None and not isinstance(clarification, bool):
            raise ValueError(
                "expected_clarification must be true, false, or absent; "
                f"got {type(clarification).__name__}"
            )

        max_tokens = _positive_budget(data.get("max_tokens"), "max_tokens")
        max_seconds = _positive_budget(data.get("max_seconds"), "max_seconds")

        return cls(
            id=str(data["id"]),
            query=str(data["query"]),
            expected_citations=[str(c) for c in data.get("expected_citations") or []],
            forbidden_phrases=[str(p) for p in data.get("forbidden_phrases") or []],
            expected_clarification=clarification,
            max_tokens=int(max_tokens) if max_tokens is not None else None,
            max_seconds=float(max_seconds) if max_seconds is not None else None,
        )


def _positive_budget(value: Any, name: str) -> float | None:
    """Validate an optional ``max_tokens``/``max_seconds`` budget.

    ``None`` (absent) is allowed and means "no gate". A present value must be a
    positive number; ``bool`` is rejected even though it is an ``int`` subclass.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive number or absent; got {value!r}")
    if value <= 0:
        raise ValueError(f"{name} must be positive; got {value!r}")
    return float(value)


def load_cases(path: str | Path) -> list[EvalCase]:
    """Load eval cases from a YAML file.

    Accepts either the scaffold's mapping form (``cases: [...]``) or a bare
    top-level list of cases. Raises ``ValueError`` if the document is neither.
    """
    raw = yaml.safe_load(Path(path).read_text())
    if raw is None:
        return []
    if isinstance(raw, dict):
        items = raw.get("cases", [])
    elif isinstance(raw, list):
        items = raw
    else:
        raise ValueError(
            f"cases file must be a mapping with a 'cases:' list or a top-level "
            f"list, got {type(raw).__name__}"
        )
    if not isinstance(items, list):
        raise ValueError(f"'cases' must be a list, got {type(items).__name__}")
    return [EvalCase.from_dict(item) for item in items]


__all__ = ["EvalCase", "load_cases"]
