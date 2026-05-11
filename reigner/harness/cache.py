"""Per-session tool-result cache (G9).

See SPEC.md §5.4 (G9) and PRINCIPLES.md §3 (bounded outputs).

Minimal stub for T-05: an in-memory dict keyed on ``(tool_name, args_hash)``.
Owned by the Session, consulted by the loop only for tools marked
``readonly=True``. A richer implementation (TTLs, size caps, eviction policy,
disk persistence) lands later if needed; the loop only depends on the
``has`` / ``get`` / ``put`` surface defined here.
"""

from __future__ import annotations

import json
from typing import Any


class ToolResultCache:
    """In-memory ``(tool_name, args) -> result`` cache for one Session.

    Stores **untruncated** results. Truncation runs on the way out so the model
    sees the same shape whether a result was just computed or served from cache.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    @staticmethod
    def _key(tool_name: str, args: dict[str, Any]) -> str:
        # sort_keys + tight separators give a deterministic, hashable string.
        # Args containing non-JSON values would have failed the @tool contract
        # upstream (PRINCIPLES §7); we don't re-validate here.
        return f"{tool_name}:{json.dumps(args, sort_keys=True, separators=(',', ':'), default=str)}"

    def has(self, tool_name: str, args: dict[str, Any]) -> bool:
        return self._key(tool_name, args) in self._store

    def get(self, tool_name: str, args: dict[str, Any]) -> Any:
        return self._store[self._key(tool_name, args)]

    def put(self, tool_name: str, args: dict[str, Any], result: Any) -> None:
        self._store[self._key(tool_name, args)] = result

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


__all__ = ["ToolResultCache"]
