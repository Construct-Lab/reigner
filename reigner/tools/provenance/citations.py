"""Citation registration — the model-facing pseudo-tool and Python read API.

SPEC §1 principle 4 ("citations are first-class") + §5.2 (``CitationEvent``)
+ §15.1 (the faithfulness eval check) together define this surface:

- ``register_citation`` is a pseudo-tool: the model emits a tool call, the
  loop intercepts it (``harness/loop.py:_dispatch_pseudo``), constructs a
  :class:`~reigner.tools.provenance.lineage.Citation`, appends it to
  ``state.citations``, and emits a :class:`CitationEvent`. Direct invocation
  raises ``NotImplementedError`` — same shape as ``save_note`` (T-08).
- ``get_citations`` is a plain module function that exposes ``state.citations``
  for Python callers: the T-29 faithfulness check, ``reigner inspect
  session``, and the citation-strict skill's prompt-composition hook.
- ``canonicalize_locator`` / ``citation_id`` produce stable string IDs for
  dedup and for the eval check's ``expected_citations`` fixtures.

The model never sees ``get_citations``: a "what have I cited?" tool would
duplicate state the model already has access to via its own conversation
history. If a future skill needs it, T-31 can add a wrapper.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from reigner.tools.base import ToolResult, tool

if TYPE_CHECKING:
    from reigner.harness.state import AgentState
    from reigner.tools.provenance.lineage import Citation


@tool(pseudo=True, readonly=True)
async def register_citation(
    source: str,
    locator: dict[str, Any],
    value: Any,
) -> ToolResult:
    """Register a citation for a fact you are about to assert.

    Use this whenever you state a numeric value or a specific factual claim
    in your final answer. The citation ties the claim to a source artifact
    and a locator inside it. Faithfulness checks (and the user) rely on
    these citations being registered before the final answer is composed.

    Do NOT use this for general context you read but did not assert. Cite the
    specific fact you used, with the smallest locator that pins it down.

    Args:
        source: A stable identifier for the source — typically a root-relative
            artifact path like ``"AAPL/2024/metrics.json"`` or a document id.
        locator: A small dict pinpointing the location within the source.
            Free-form; common shapes include ``{"field": "<name>"}`` for JSON
            fields, ``{"line": 42}`` for text, ``{"section": "sections/risks"}``
            for artifact sections. Use the smallest locator that uniquely
            identifies the cited fact.
        value: The actual cited value — a number, short string, or small JSON
            object. The value the final answer is going to assert.
    """
    raise NotImplementedError(
        "register_citation is a pseudo-tool intercepted by the loop; "
        "direct invocation is not supported."
    )


def canonicalize_locator(locator: dict[str, Any]) -> str:
    """Render a locator dict to a deterministic string for identity / dedup.

    Empty dict canonicalizes to ``""``. Flat ``str``/``int``/``float``/``bool``
    values render as ``k=v`` joined by ``&`` with keys sorted lexicographically.
    Nested values are JSON-serialized with sorted keys so two semantically
    equivalent locators always produce the same canonical form. Non-string
    keys are coerced via ``str()`` to keep this total — typed contracts
    upstream are responsible for shape, not this function.
    """
    if not locator:
        return ""
    parts: list[str] = []
    for k in sorted(locator, key=str):
        v = locator[k]
        if isinstance(v, str | int | float | bool) or v is None:
            rendered = str(v)
        else:
            rendered = json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)
        parts.append(f"{k}={rendered}")
    return "&".join(parts)


def citation_id(source: str, locator: dict[str, Any]) -> str:
    """Stable string identifier for a citation: ``f"{source}#{canonical}"``.

    When the locator is empty the trailing ``#`` is omitted so a bare-source
    citation is just the source string. Used by ``state.add_citation`` for
    dedup and by the faithfulness eval (T-29) for comparison against
    ``EvalCase.expected_citations``.
    """
    canonical = canonicalize_locator(locator)
    if not canonical:
        return source
    return f"{source}#{canonical}"


def get_citations(state: AgentState) -> list[Citation]:
    """Return a copy of the citations registered on ``state``.

    Plain accessor: returns a list copy so callers can't mutate the session's
    citation log. T-29 (faithfulness) iterates this list to verify every
    numeric claim in the final answer maps to a registered citation.
    """
    return list(state.citations)


__all__ = [
    "canonicalize_locator",
    "citation_id",
    "get_citations",
    "register_citation",
]
