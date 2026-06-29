"""Citation lineage — per-citation provenance record.

Citations are first-class. The wire event
(``harness.events.CitationEvent``) only carries the bare claim — source,
locator, value. ``Citation`` adds the local-state fields the loop captures
when it intercepts a ``register_citation`` call: the turn the citation was
registered on, and the model-side tool-call id that produced it.

``tool_name`` is included because future intercepted callers (a tool that
auto-cites on its own behalf, an eval harness replaying a session) may set
something other than the literal ``"register_citation"`` — leaving the field
open keeps the schema honest about its source.

The dataclass is intentionally inert: no methods, no validation. The loop
constructs it; ``state.add_citation`` enforces identity / dedup; tests and
the eval check read fields directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(kw_only=True)
class Citation:
    """One registered citation in a session.

    Fields:
        source: a stable string identifier for the source artifact — typically
            a root-relative artifact path (``"AAPL/2024/metrics.json"``) but
            free-form so non-artifact sources (URLs, BM25 doc ids) work too.
        locator: free-form structured locator within the source. The shape is
            tool-specific (see ``canonicalize_locator`` for the identity rule
            applied for dedup).
        value: the actual claim being cited — typically a number, string, or
            short JSON. ``Any`` because callers vary widely.
        turn: the loop iteration the citation was registered on. Useful for
            ``reigner inspect session`` and for ordering in faithfulness checks.
        tool_call_id: the model-emitted tool-call id of the ``register_citation``
            invocation. ``None`` if the citation was constructed outside the
            loop (e.g. tests, replays).
        tool_name: the name of the intercepted tool that produced the citation.
            Almost always ``"register_citation"``; reserved for future callers.
        ts: registration timestamp.
    """

    source: str
    locator: dict[str, Any]
    value: Any
    turn: int
    tool_call_id: str | None = None
    tool_name: str | None = None
    ts: datetime = field(default_factory=_utcnow)


__all__ = ["Citation"]
