"""Markdown loader with optional YAML front-matter parsing.

Front-matter is the YAML block between leading ``---`` delimiters. When
present and parseable as a mapping it lands in ``meta["frontmatter"]``;
otherwise it is silently ignored and the file is treated as plain
markdown. The full bytes (front-matter included) are returned as
``raw`` — stripping it is a domain decision the extractor owns.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import yaml

from reigner.ingestion.loaders.base import LoadedDocument

_DELIM = "---"


class MdLoader:
    """Reads a markdown file; parses YAML front-matter if present."""

    extensions: ClassVar[frozenset[str]] = frozenset({".md", ".markdown"})

    def __init__(
        self,
        meta_extractor: Callable[[Path], dict[str, Any]] | None = None,
    ) -> None:
        self._meta_extractor = meta_extractor

    async def load(self, source: str | Path) -> LoadedDocument:
        path = Path(source)
        raw = await asyncio.to_thread(path.read_bytes)
        meta: dict[str, Any] = {
            "source": str(path),
            "filename": path.name,
            "size_bytes": len(raw),
            "content_type": "text/markdown",
        }
        frontmatter = _parse_frontmatter(raw)
        if frontmatter is not None:
            meta["frontmatter"] = frontmatter
        if self._meta_extractor is not None:
            meta.update(self._meta_extractor(path))
        return LoadedDocument(raw=raw, meta=meta)


def _parse_frontmatter(raw: bytes) -> dict[str, Any] | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != _DELIM:
        return None
    try:
        end = lines.index(_DELIM, 1)
    except ValueError:
        return None
    block = "\n".join(lines[1:end])
    try:
        parsed = yaml.safe_load(block)
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None
