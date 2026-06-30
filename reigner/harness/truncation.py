"""Per-tool result truncation (G2).

The budget is measured against the JSON-serialized form of the result, which
is what actually enters the model context. Truncation respects JSON boundaries:

- **str**: hard slice with a trailing marker.
- **list**: keep the longest prefix whose serialized envelope fits; wrap with
  ``_truncated`` / ``_original_count``. Items themselves are kept whole — we do
  not split an item to half-fit.
- **dict**: keep insertion-order items whose envelope fits; wrap with
  ``_truncated`` / ``_original_keys`` / ``available_keys`` (the keys the model
  could re-request to see what was dropped). If a single value is too large to
  fit, recursively truncate it rather than dropping the key entirely.
- **other**: re-encoded to a string and sliced.

Every truncated result tells the model so via explicit markers — the model can
request more without unbounded calls.
"""

from __future__ import annotations

import json
from typing import Any

_TRUNCATION_SUFFIX = "... [truncated]"


def _serialized_size(value: Any) -> int:
    return len(json.dumps(value, default=str))


def resolve_limit(tool_name: str, char_limits: dict[str, int], default: int) -> int:
    """Resolve the effective char limit for ``tool_name``.

    Centralised so the loop, tests, and any future plugin surface read the
    override table the same way.
    """
    return char_limits.get(tool_name, default)


def truncate_for_tool(result: Any, char_limit: int) -> tuple[Any, bool]:
    """Return ``(possibly-truncated result, was_truncated)``.

    A ``char_limit`` of 0 (or negative) disables truncation — used by eval
    profiles that want raw, unbounded tool output.
    """
    if char_limit <= 0:
        return result, False
    if _serialized_size(result) <= char_limit:
        return result, False
    return _truncate(result, char_limit), True


def _truncate(result: Any, char_limit: int) -> Any:
    if isinstance(result, str):
        keep = max(0, char_limit - len(_TRUNCATION_SUFFIX))
        return result[:keep] + _TRUNCATION_SUFFIX

    if isinstance(result, list):
        return _truncate_list(result, char_limit)

    if isinstance(result, dict):
        return _truncate_dict(result, char_limit)

    serialized = json.dumps(result, default=str)
    return {
        "_truncated": True,
        "_value": serialized[: max(0, char_limit - len(_TRUNCATION_SUFFIX))] + _TRUNCATION_SUFFIX,
    }


def _truncate_list(result: list[Any], char_limit: int) -> dict[str, Any]:
    """Keep the longest item prefix whose envelope fits."""
    envelope = {"items": [], "_truncated": True, "_original_count": len(result)}
    base_size = _serialized_size(envelope)
    kept: list[Any] = []
    for item in result:
        item_size = _serialized_size(item) + 1  # +1 for the comma separator
        if base_size + item_size > char_limit:
            break
        kept.append(item)
        base_size += item_size
    return {
        "items": kept,
        "_truncated": True,
        "_original_count": len(result),
    }


def _truncate_dict(result: dict[str, Any], char_limit: int) -> dict[str, Any]:
    """Keep insertion-order items whose envelope fits; recurse into oversized values.

    ``available_keys`` lists the keys that were dropped (or recursively
    truncated) so the model can re-request them via a follow-up tool call.
    """
    original_keys = list(result.keys())
    truncated: dict[str, Any] = {
        "_truncated": True,
        "_original_keys": original_keys,
        "available_keys": [],
    }
    dropped: list[str] = []
    for k, v in result.items():
        candidate = {**truncated, k: v}
        if _serialized_size(candidate) <= char_limit:
            truncated = candidate
            continue
        # Try recursively truncating just this value into the remaining budget.
        remaining = char_limit - _serialized_size(truncated) - len(json.dumps(k)) - 2
        if remaining > 0 and isinstance(v, str | list | dict):
            truncated_value = _truncate(v, remaining)
            tentative = {**truncated, k: truncated_value}
            if _serialized_size(tentative) <= char_limit:
                truncated = tentative
                continue
        dropped.append(k)
    truncated["available_keys"] = dropped
    return truncated


__all__ = ["resolve_limit", "truncate_for_tool"]
