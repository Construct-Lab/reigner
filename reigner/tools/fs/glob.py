"""fs_glob — pattern-based path listing under the FsTools sandbox."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from reigner.tools.base import tool

if TYPE_CHECKING:
    from reigner.tools.fs.store import FsTools


def build_fs_glob(fs: FsTools) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build a @tool closure over ``fs``.

    Patterns use ``pathlib``-style globbing — ``**`` walks recursively,
    ``*`` matches a single segment, ``?`` matches one character. The
    pattern is always interpreted relative to ``base`` (default: the
    sandbox root).
    """

    @tool(readonly=True)
    async def fs_glob(
        pattern: str, base: str | None = None, include_hidden: bool = False
    ) -> dict[str, Any]:
        """Match paths against a glob pattern.

        Args:
            pattern: Glob pattern (e.g. ``**/*.py`` or ``src/*.ts``).
            base: Optional root-relative directory to glob from. Defaults
                to the sandbox root.
            include_hidden: When False (default), paths under dotfile
                segments or ignored directories are filtered out.

        Returns:
            ``{paths, truncated, count}``. ``paths`` is a sorted list of
            root-relative POSIX strings, capped at ``max_glob_results``.
        """
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("pattern must be a non-empty string")
        if pattern.startswith("/"):
            raise ValueError(f"pattern must be relative, got {pattern!r}")

        root = fs.root if base is None else fs.resolve(base)
        if not root.is_dir():
            raise NotADirectoryError(f"glob base is not a directory: {base!r}")

        paths: list[str] = []
        truncated = False
        for match in sorted(root.glob(pattern)):
            if fs.is_ignored(match, include_hidden=include_hidden):
                continue
            try:
                match.relative_to(fs.root)
            except ValueError:
                continue
            paths.append(str(match.relative_to(fs.root).as_posix()))
            if len(paths) >= fs.max_glob_results:
                truncated = True
                break

        return {"paths": paths, "truncated": truncated, "count": len(paths)}

    return fs_glob


__all__ = ["build_fs_glob"]
