"""Filter parser and matcher for sidecar `identifiers` dicts.

The filter language is intentionally tiny so an agent can use it without
prose. A filter is a mapping from identifier key to either a scalar string
(exact match) or a list of strings (OR within the key). Multiple keys are
AND-ed. Anything richer (ranges, regex, negation) is deferred until a real
use case asks for it.
"""

from __future__ import annotations

from typing import Any

Filter = dict[str, str | list[str]]
"""Public filter type. Values are either a string or a list of strings."""


class FilterError(ValueError):
    """Raised when a caller-supplied filter is malformed."""


def parse_filters(raw: dict[str, Any] | None) -> Filter:
    """Validate and normalize a caller-supplied filter mapping.

    Returns a fresh dict so the caller can't mutate internal state. Empty
    or None input yields an empty filter (matches every entry).
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise FilterError(f"filters must be a dict, got {type(raw).__name__}")
    out: Filter = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise FilterError(f"filter key must be a non-empty string, got {key!r}")
        if isinstance(value, str):
            out[key] = value
        elif isinstance(value, list):
            if not value:
                raise FilterError(f"filter {key!r}: list value must be non-empty")
            if not all(isinstance(v, str) for v in value):
                raise FilterError(f"filter {key!r}: list values must all be strings")
            out[key] = list(value)
        else:
            raise FilterError(
                f"filter {key!r}: value must be a string or list of strings, "
                f"got {type(value).__name__}"
            )
    return out


def matches(entry_identifiers: dict[str, str], filter_: Filter) -> bool:
    """Return True iff every filter key matches a value in `entry_identifiers`.

    A missing identifier is treated as a non-match. List values OR within
    a single key; multiple keys AND across keys.
    """
    for key, expected in filter_.items():
        actual = entry_identifiers.get(key)
        if actual is None:
            return False
        if isinstance(expected, str):
            if actual != expected:
                return False
        else:
            if actual not in expected:
                return False
    return True


__all__ = ["Filter", "FilterError", "matches", "parse_filters"]
