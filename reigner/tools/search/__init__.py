"""Pluggable search surface.

`SearchIndex` is the protocol every retrieval backend must satisfy: a backend
is anything that hands the harness a list of registered tool callables.
v0 ships `Bm25Index`, a JSON-sidecar BM25 backend. Vector and SQL backends are
contributable post-v0; they declare their own tool names via `tools()`.
"""

from reigner.tools.search.base import SearchIndex
from reigner.tools.search.bm25 import Bm25Index

__all__ = ["Bm25Index", "SearchIndex"]
