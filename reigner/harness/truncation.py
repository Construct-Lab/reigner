"""Per-tool result truncation (G2).

See SPEC.md §5.4 (G2) and PRINCIPLES.md §3 (bounded outputs).

Stub for T-05: char-based, JSON-aware best-effort. The richer implementation
that respects per-tool budgets and JSON-structure boundaries lands as the
artifact tools land (T-09 onwards). The loop only needs the
``truncate_for_tool`` callable defined here.

The discipline (PRINCIPLES §3): when we truncate, the returned shape says so
explicitly via a ``_truncated`` marker so the model knows it can ask for more.
"""

from __future__ import annotations

import json
from typing import Any

_TRUNCATION_SUFFIX = "... [truncated]"


def _serialized_size(value: Any) -> int:
    return len(json.dumps(value, default=str))


def truncate_for_tool(result: Any, char_limit: int) -> tuple[Any, bool]:
    """Return ``(possibly-truncated result, was_truncated)``.

    Strategy by type:
      - **str**: hard slice with a trailing marker.
      - **list**: keep the longest prefix whose serialized size fits.
      - **dict**: keep the largest prefix of items (insertion order) that fits;
        wrap with a ``_truncated`` marker.
      - **other JSON-coercible**: re-encoded to a string and sliced.

    The char limit is checked against the JSON-serialized form so the budget
    matches what actually goes into the model context.
    """
    if char_limit <= 0:
        return result, False
    if _serialized_size(result) <= char_limit:
        return result, False

    if isinstance(result, str):
        keep = max(0, char_limit - len(_TRUNCATION_SUFFIX))
        return result[:keep] + _TRUNCATION_SUFFIX, True

    if isinstance(result, list):
        kept: list[Any] = []
        for item in result:
            candidate = {
                "items": [*kept, item],
                "_truncated": True,
                "_original_count": len(result),
            }
            if _serialized_size(candidate) > char_limit:
                break
            kept.append(item)
        return {
            "items": kept,
            "_truncated": True,
            "_original_count": len(result),
        }, True

    if isinstance(result, dict):
        original_keys = list(result.keys())
        truncated: dict[str, Any] = {
            "_truncated": True,
            "_original_keys": original_keys,
        }
        for k, v in result.items():
            candidate = {**truncated, k: v}
            if _serialized_size(candidate) > char_limit:
                break
            truncated = candidate
        return truncated, True

    # Fallback: stringify and slice.
    serialized = json.dumps(result, default=str)
    return {
        "_truncated": True,
        "_value": serialized[: max(0, char_limit - len(_TRUNCATION_SUFFIX))] + _TRUNCATION_SUFFIX,
    }, True


__all__ = ["truncate_for_tool"]
