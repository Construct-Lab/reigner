"""Per-session tool-result cache (G9).

In-memory ``(tool_name, args_hash) -> result`` cache, owned by the Session and
consulted by the loop **only for tools marked ``readonly=True``**. The invariant
is enforced at the call site (loop.py); the cache itself never inspects tool
metadata, so it stays a dumb keyed store. Caching a non-readonly tool would let
a write be silently skipped on replay.

Errors are not cached. The loop only calls ``put`` on successful results, so a
transient failure can be retried on the next iteration.

Out of scope here: TTLs, size caps, eviction policy, disk persistence. The
loop only depends on the ``has`` / ``get`` / ``put`` / ``stats`` surface.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CacheStats:
    """Snapshot of cache counters. Returned by :meth:`ToolResultCache.stats`."""

    hits: int
    misses: int
    size: int


class ToolResultCache:
    """In-memory ``(tool_name, args) -> result`` cache for one Session.

    Stores **untruncated** results. Truncation runs on the way out so the model
    sees the same shape whether a result was just computed or served from cache.

    Hit/miss counters are updated by :meth:`has` (the loop's branching point):
    a ``True`` return increments ``hits``, ``False`` increments ``misses``.
    ``get`` does not double-count; it assumes ``has`` was just consulted.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._hits: int = 0
        self._misses: int = 0

    @staticmethod
    def key(tool_name: str, args: dict[str, Any]) -> str:
        """Deterministic cache key for ``(tool_name, args)``.

        Args are JSON-encoded with sorted keys, so call order does not matter.
        ``default=str`` keeps the cache forgiving of datetime/Path-shaped args
        the model occasionally produces; @tool validation upstream rejects
        anything truly non-coercible.
        """
        return f"{tool_name}:{json.dumps(args, sort_keys=True, separators=(',', ':'), default=str)}"

    def has(self, tool_name: str, args: dict[str, Any]) -> bool:
        """Return whether a result is cached, updating hit/miss counters."""
        present = self.key(tool_name, args) in self._store
        if present:
            self._hits += 1
        else:
            self._misses += 1
        return present

    def get(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Return the cached result for ``(tool_name, args)``."""
        return self._store[self.key(tool_name, args)]

    def put(self, tool_name: str, args: dict[str, Any], result: Any) -> None:
        """Store ``result`` under the key for ``(tool_name, args)``."""
        self._store[self.key(tool_name, args)] = result

    def clear(self) -> None:
        """Drop all cached results and reset the hit/miss counters."""
        self._store.clear()
        self._hits = 0
        self._misses = 0

    def stats(self) -> CacheStats:
        """Return a snapshot of the cache's hit/miss/size counters."""
        return CacheStats(hits=self._hits, misses=self._misses, size=len(self._store))

    def __len__(self) -> int:
        return len(self._store)


__all__ = ["CacheStats", "ToolResultCache"]
