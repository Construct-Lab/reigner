"""fs_ls — directory listing under the FsTools sandbox."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from reigner.tools.base import tool

if TYPE_CHECKING:
    from reigner.tools.fs.store import FsTools


def build_fs_ls(fs: FsTools) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build a @tool closure over ``fs``."""

    @tool(readonly=True)
    async def fs_ls(path: str = ".", include_hidden: bool = False) -> dict[str, Any]:
        """List entries directly under a directory.

        Args:
            path: Root-relative directory. ``"."`` lists the root itself.
            include_hidden: Include dotfile entries in the result. Ignored
                directory names (``.git``, ``node_modules``, etc.) are
                still filtered out regardless of this flag.

        Returns:
            ``{entries, truncated, count}``. ``entries`` is a sorted list
            of ``{name, type, size}`` (``type`` is ``"file"`` or ``"dir"``;
            ``size`` is bytes for files and ``None`` for dirs), capped at
            ``max_ls_entries``.
        """
        target = fs.root if path == "." else fs.resolve(path)
        if not target.is_dir():
            raise NotADirectoryError(f"not a directory: {path!r}")

        children = sorted(target.iterdir(), key=lambda p: p.name)
        entries: list[dict[str, Any]] = []
        truncated = False
        for child in children:
            name = child.name
            if name in fs.ignored_dirs:
                continue
            if not include_hidden and name.startswith("."):
                continue
            if child.is_dir():
                kind: str = "dir"
                size: int | None = None
            elif child.is_file():
                kind = "file"
                try:
                    size = child.stat().st_size
                except OSError:
                    size = None
            else:
                continue
            entries.append({"name": name, "type": kind, "size": size})
            if len(entries) >= fs.max_ls_entries:
                truncated = True
                break

        return {"entries": entries, "truncated": truncated, "count": len(entries)}

    return fs_ls


__all__ = ["build_fs_ls"]
