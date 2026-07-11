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
            base: Optional virtual-tree directory to glob from (e.g.
                ``backend`` scopes to one root). When omitted, the pattern
                is matched under every configured root.
            include_hidden: When False (default), paths under dotfile
                segments or ignored directories are filtered out.

        Returns:
            ``{paths, truncated, count}``. ``paths`` is a list of virtual-tree
            POSIX strings (root-prefixed when multiple roots are configured),
            sorted within each root, capped at ``max_glob_results``.
        """
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("pattern must be a non-empty string")
        if pattern.startswith("/"):
            raise ValueError(f"pattern must be relative, got {pattern!r}")

        # One scoped base when given, otherwise fan out across every root.
        if base is None:
            glob_roots = fs.iter_roots()
        else:
            root_name, resolved = fs.resolve(base)
            if not resolved.is_dir():
                raise NotADirectoryError(f"glob base is not a directory: {base!r}")
            glob_roots = [(root_name, resolved)]

        paths: list[str] = []
        truncated = False
        for root_name, gbase in glob_roots:
            root_base = fs.roots[root_name]
            for match in sorted(gbase.glob(pattern)):
                if fs.is_ignored(match, root_base, include_hidden=include_hidden):
                    continue
                try:
                    match.relative_to(root_base)
                except ValueError:
                    continue
                paths.append(fs.display(root_name, match))
                if len(paths) >= fs.max_glob_results:
                    truncated = True
                    break
            if truncated:
                break

        return {"paths": paths, "truncated": truncated, "count": len(paths)}

    return fs_glob


__all__ = ["build_fs_glob"]
