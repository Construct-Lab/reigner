"""fs_read — bounded text-mode reads under the FsTools sandbox."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from reigner.tools.base import tool

if TYPE_CHECKING:
    from reigner.tools.fs.store import FsTools


def build_fs_read(fs: FsTools) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build a @tool closure over ``fs``."""
    default_limit = fs.max_read_chars

    @tool(readonly=True)
    async def fs_read(path: str, offset: int = 0, limit: int = default_limit) -> dict[str, Any]:
        """Read a chunk of a text file under the fs root.

        Args:
            path: Virtual-tree path (e.g. ``src/loop.py``, or
                ``backend/src/loop.py`` when multiple roots are configured).
            offset: Character offset to start at.
            limit: Maximum characters to return. Capped at ``max_read_chars``.

        Returns:
            ``{content, offset, limit, has_more, total_size}``. Binary files
            (suffix outside the allowlist) are rejected with a clear error.
        """
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        if limit <= 0:
            raise ValueError(f"limit must be > 0, got {limit}")
        if limit > fs.max_read_chars:
            limit = fs.max_read_chars
        _root_name, target = fs.resolve(path)
        if not target.is_file():
            raise FileNotFoundError(f"no file at {path!r}")
        if not fs.is_text_extension(target):
            raise ValueError(
                f"{path!r} is not a readable text file "
                f"(suffix {target.suffix!r} not in fs.text_extensions)"
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

    return fs_read


__all__ = ["build_fs_read"]
