"""Provenance and citations.

The :func:`register_citation` pseudo-tool is locally intercepted by the loop
exactly like the verbs in :mod:`reigner.tools.pseudo` — the package is
separate because citation tracking is a distinct concern from loop self-
management. The loop unions :data:`PROVENANCE_TOOL_NAMES` with
:data:`reigner.tools.pseudo.PSEUDO_TOOL_NAMES` to build its dispatch set.
"""

from reigner.tools.provenance.citations import (
    canonicalize_locator,
    citation_id,
    get_citations,
    register_citation,
)
from reigner.tools.provenance.lineage import Citation

PROVENANCE_TOOL_NAMES: frozenset[str] = frozenset({"register_citation"})

__all__ = [
    "PROVENANCE_TOOL_NAMES",
    "Citation",
    "canonicalize_locator",
    "citation_id",
    "get_citations",
    "register_citation",
]
