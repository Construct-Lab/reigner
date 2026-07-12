"""``coverage`` eval check — did the agent retrieve the right artifacts?

Distinct from ``faithfulness`` (which scores *citing*), coverage scores
*retrieving*: for a case whose ``expected_citations`` name the artifacts that
contain the answer, did the agent actually read/grep those sources? An agent can
fail coverage by guessing without retrieval even when its prose happens to be
right.

Deterministic — it reads only ``run.events``. Ground truth is the *source* of
each expected citation: the part of the ``citation_id`` string before ``#``
(e.g. ``"AAPL/2024/metrics.json#field=rnd"`` → ``"AAPL/2024/metrics.json"``).
"Retrieved" means one of:

- a :class:`~reigner.harness.events.ToolCallEvent` carried the path in a
  ``path`` / ``file_path`` / ``entity`` argument — the keys used by
  ``read_artifact_file``, ``get_json_field``, and ``grep_artifact`` (``entity``
  scopes the search to a directory, which the prefix match below then treats as
  retrieving everything under it); or
- a :class:`~reigner.harness.events.ToolResultEvent` reported a resolved
  ``path`` in its result — how ``get_section`` names its target, since its call
  args are ``section`` + identifiers rather than a path.

A retrieved path covers an expected source when they are equal or one is a
path-segment prefix of the other (so reading a directory or a file under it
both count).

Verdicts:

- ``na``   — the case declares no ``expected_citations`` (nothing to require).
- ``pass`` — every expected source was retrieved.
- ``fail`` — one or more sources were never retrieved; the detail lists them.
"""

from __future__ import annotations

from reigner.eval.cases import EvalCase
from reigner.eval.checks import CaseRun, CheckResult, check
from reigner.harness.events import ToolCallEvent, ToolResultEvent

# Tool arguments that name an artifact path or scope: read_artifact_file /
# get_json_field use ``path``; grep_artifact uses ``file_path`` or an ``entity``
# directory (e.g. ``AAPL/2024``), which the prefix match in ``_covers`` then
# treats as retrieving everything under it.
_PATH_KEYS = ("path", "file_path", "entity")


def _expected_source(citation: str) -> str:
    """The source path of an expected citation (everything before ``#``)."""
    return citation.split("#", 1)[0]


def _retrieved_paths(run: CaseRun) -> set[str]:
    paths: set[str] = set()
    for event in run.events:
        if isinstance(event, ToolCallEvent):
            for key in _PATH_KEYS:
                value = event.args.get(key)
                if isinstance(value, str) and value:
                    paths.add(value)
        elif isinstance(event, ToolResultEvent):
            # ``get_section`` names its target by section + identifiers, not a
            # path arg — the resolved path is only in the result. Pick it up here
            # so an idiomatic section read counts as retrieval.
            result = event.result
            if isinstance(result, dict):
                value = result.get("path")
                if isinstance(value, str) and value:
                    paths.add(value)
    return paths


def _covers(retrieved: str, source: str) -> bool:
    a, b = retrieved.rstrip("/"), source.rstrip("/")
    return a == b or b.startswith(a + "/") or a.startswith(b + "/")


@check("coverage")
def coverage(case: EvalCase, run: CaseRun) -> CheckResult:
    """Fail if any expected-citation source was never retrieved; ``na`` if none."""
    sources = {_expected_source(c) for c in case.expected_citations}
    if not sources:
        return CheckResult("coverage", "na", "no expected citations")

    retrieved = _retrieved_paths(run)
    uncovered = sorted(s for s in sources if not any(_covers(p, s) for p in retrieved))
    if uncovered:
        return CheckResult("coverage", "fail", "uncovered: " + ", ".join(uncovered))
    return CheckResult("coverage", "pass")


__all__ = ["coverage"]
