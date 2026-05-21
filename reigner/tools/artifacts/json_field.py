"""get_json_field — top-level field extraction from a JSON artifact.

Top-level only by design. Deep traversal (jsonpath, dotted keys) is deferred
to a separate ``get_json_path`` tool if real schemas ever need it — keeps the
bounded-output contract on this tool simple. See implementation plan §06.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from reigner.tools.base import tool

if TYPE_CHECKING:
    from reigner.tools.artifacts.store import ArtifactStore


def build_get_json_field(
    store: ArtifactStore,
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build a @tool closure over ``store``."""

    @tool(readonly=True)
    async def get_json_field(path: str, fields: list[str]) -> dict[str, Any]:
        """Return selected top-level fields of a JSON artifact.

        Args:
            path: Root-relative path to a ``.json`` artifact.
            fields: Top-level field names to extract.

        Returns:
            ``{fields, available_keys, missing_keys}``. ``available_keys`` is
            the full list of top-level keys in the file so the model can
            re-query without guessing; ``missing_keys`` lists any requested
            fields not present.
        """
        if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields):
            raise ValueError("fields must be a list of strings")
        target = store.resolve(path)
        if not target.is_file():
            raise FileNotFoundError(f"no artifact at {path!r}")
        if target.suffix.lower() != ".json":
            raise ValueError(f"{path!r} is not a .json artifact")
        try:
            data = json.loads(target.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path!r} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{path!r} top-level must be a JSON object, got {type(data).__name__}")
        available = sorted(data.keys())
        present = {f: data[f] for f in fields if f in data}
        missing = [f for f in fields if f not in data]
        return {
            "fields": present,
            "available_keys": available,
            "missing_keys": missing,
        }

    return get_json_field


__all__ = ["build_get_json_field"]
