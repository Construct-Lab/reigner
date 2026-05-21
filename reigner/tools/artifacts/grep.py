"""grep_artifact — literal substring search across text artifacts.

Literal-only by design. Adding a regex flag is deferred (see implementation
plan §06): regex without a per-pattern timeout is a ReDoS hazard, and v0 has
no real-world signal that the model needs regex over literals.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from reigner.tools.artifacts.extensions import is_text_file
from reigner.tools.base import tool

if TYPE_CHECKING:
    from reigner.tools.artifacts.store import ArtifactStore

_MAX_MATCHES = 10


def build_grep_artifact(
    store: ArtifactStore,
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build a @tool closure over ``store``."""

    @tool(readonly=True)
    async def grep_artifact(
        query: str,
        entity: str | None = None,
        file_path: str | None = None,
        extensions: list[str] | None = None,
        case_insensitive: bool = False,
    ) -> dict[str, Any]:
        """Find literal substring matches across text artifacts.

        Args:
            query: Literal substring to search for. Not a regex.
            entity: Optional root-relative entity directory to limit the
                search (e.g. ``AAPL/2024``).
            file_path: Optional root-relative file to search within. When set,
                ``entity`` and ``extensions`` are ignored.
            extensions: Restrict to files with these suffixes. Each entry
                must start with ``.``. When omitted, every file the schema
                considers text-readable is searched (suffixless section
                files included).
            case_insensitive: Match without case sensitivity.

        Returns:
            ``{matches, total_files_searched, truncated}``. ``matches`` is a
            list of ``{path, line, line_no}`` (1-indexed line_no), capped at
            10 entries; ``truncated=True`` when the cap was hit.
        """
        if not isinstance(query, str) or not query:
            raise ValueError("query must be a non-empty string")
        suffixes = _normalise_extensions(extensions)

        if file_path is not None:
            search_paths: list[Path] = [store.resolve(file_path)]
        else:
            base = store.resolve(entity) if entity else store.root
            if not base.exists():
                raise FileNotFoundError(f"no artifact at {entity!r}" if entity else "empty root")
            search_paths = sorted(p for p in base.rglob("*") if p.is_file())

        needle = query.casefold() if case_insensitive else query
        matches: list[dict[str, Any]] = []
        files_searched = 0
        truncated = False

        for target in search_paths:
            if not target.is_file():
                continue
            if suffixes is not None and target.suffix.lower() not in suffixes:
                continue
            if not is_text_file(target, store.schema):
                continue
            files_searched += 1
            try:
                text = target.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            rel = str(target.relative_to(store.root))
            for line_no, line in enumerate(text.splitlines(), start=1):
                hay = line.casefold() if case_insensitive else line
                if needle in hay:
                    matches.append({"path": rel, "line_no": line_no, "line": line})
                    if len(matches) >= _MAX_MATCHES:
                        truncated = True
                        break
            if truncated:
                break

        return {
            "matches": matches,
            "total_files_searched": files_searched,
            "truncated": truncated,
        }

    return grep_artifact


def _normalise_extensions(extensions: list[str] | None) -> frozenset[str] | None:
    if extensions is None:
        return None
    out: set[str] = set()
    for ext in extensions:
        if not isinstance(ext, str) or not ext.startswith("."):
            raise ValueError(f"extension {ext!r} must start with '.'")
        out.add(ext.lower())
    return frozenset(out)


__all__ = ["build_grep_artifact"]
