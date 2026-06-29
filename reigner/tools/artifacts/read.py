"""read_artifact_file — bounded text-mode reads with offset/limit pagination."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from reigner.tools.artifacts.extensions import is_text_file
from reigner.tools.base import tool

if TYPE_CHECKING:
    from reigner.tools.artifacts.store import ArtifactStore


def build_read_artifact_file(
    store: ArtifactStore,
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build a @tool closure over ``store`` for reading an artifact file."""

    @tool(readonly=True)
    async def read_artifact_file(path: str, offset: int = 0, limit: int = 4000) -> dict[str, Any]:
        """Read a chunk of a text artifact under the artifact root.

        Args:
            path: Root-relative path to the artifact (e.g. ``AAPL/2024/metrics.json``).
            offset: Character offset to start at.
            limit: Maximum characters to return.

        Returns:
            ``{content, offset, limit, has_more, total_size}``.
        """
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        if limit <= 0:
            raise ValueError(f"limit must be > 0, got {limit}")
        target = store.resolve(path)
        if not target.is_file():
            raise FileNotFoundError(f"no artifact at {path!r}")
        if not is_text_file(target, store.schema):
            raise ValueError(
                f"{path!r} is not a readable text artifact "
                f"(suffix {target.suffix!r} not in schema.text_extensions)"
            )
        text = target.read_text()
        chunk = text[offset : offset + limit]
        return {
            "content": chunk,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < len(text),
            "total_size": len(text),
        }

    return read_artifact_file


__all__ = ["build_read_artifact_file"]
