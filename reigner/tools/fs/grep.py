"""fs_grep — literal substring search across text files in the sandbox.

Literal-only by design — mirrors ``grep_artifact``. Regex without a
per-pattern timeout is a ReDoS hazard, and there's no real-world signal
yet that the model needs regex over literals in code search.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from reigner.tools.base import tool

if TYPE_CHECKING:
    from reigner.tools.fs.store import FsTools


def build_fs_grep(fs: FsTools) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build a @tool closure over ``fs``."""

    @tool(readonly=True)
    async def fs_grep(
        query: str,
        path: str | None = None,
        extensions: list[str] | None = None,
        case_insensitive: bool = False,
        include_hidden: bool = False,
    ) -> dict[str, Any]:
        """Find literal substring matches across text files.

        Args:
            query: Literal substring to search for. Not a regex.
            path: Optional virtual-tree directory or file to limit the
                search (e.g. ``backend`` scopes to one root, ``backend/app``
                to a subtree). When omitted, searches every root.
            extensions: Restrict to files with these suffixes (each must
                start with ``.``). When omitted, defaults to
                ``fs.text_extensions``.
            case_insensitive: Match without case sensitivity.
            include_hidden: When False (default), dotfile and ignored
                directories are skipped during the walk.

        Returns:
            ``{matches, total_files_searched, truncated}``. ``matches`` is
            a list of ``{path, line_no, line}`` (1-indexed ``line_no``,
            root-prefixed ``path`` when multiple roots are configured),
            capped at ``max_grep_matches``.
        """
        if not isinstance(query, str) or not query:
            raise ValueError("query must be a non-empty string")
        suffixes = _normalise_extensions(extensions) or fs.text_extensions

        # Determine which (root_name, base) pairs to walk: one scoped base when
        # a path is given, otherwise fan out across every configured root.
        if path:
            root_name, base = fs.resolve(path)
            if not base.exists():
                raise FileNotFoundError(f"no path at {path!r}")
            search_roots = [(root_name, base)]
        else:
            search_roots = fs.iter_roots()

        needle = query.casefold() if case_insensitive else query
        matches: list[dict[str, Any]] = []
        files_searched = 0
        truncated = False

        for root_name, base in search_roots:
            root_base = fs.roots[root_name]
            if base.is_file():
                search_paths: list[Path] = [base]
            else:
                search_paths = sorted(
                    p
                    for p in base.rglob("*")
                    if p.is_file()
                    and not fs.is_ignored(p, root_base, include_hidden=include_hidden)
                )
            for target in search_paths:
                if target.suffix.lower() not in suffixes:
                    continue
                files_searched += 1
                try:
                    text = target.read_text()
                except (OSError, UnicodeDecodeError):
                    continue
                rel = fs.display(root_name, target)
                for line_no, line in enumerate(text.splitlines(), start=1):
                    hay = line.casefold() if case_insensitive else line
                    if needle in hay:
                        matches.append({"path": rel, "line_no": line_no, "line": line})
                        if len(matches) >= fs.max_grep_matches:
                            truncated = True
                            break
                if truncated:
                    break
            if truncated:
                break

        return {
            "matches": matches,
            "total_files_searched": files_searched,
            "truncated": truncated,
        }

    return fs_grep


def _normalise_extensions(extensions: list[str] | None) -> frozenset[str] | None:
    if extensions is None:
        return None
    out: set[str] = set()
    for ext in extensions:
        if not isinstance(ext, str) or not ext.startswith("."):
            raise ValueError(f"extension {ext!r} must start with '.'")
        out.add(ext.lower())
    return frozenset(out)


__all__ = ["build_fs_grep"]
