"""JSON / JSONL loader.

Bytes are passed through unchanged so the extractor can parse (or not)
on its own terms. Meta records ``format`` (``"json"`` vs ``"jsonl"``)
and, for JSONL, the non-blank line count.

The module is named ``json_doc`` rather than ``json`` to avoid shadowing
the stdlib module within this subpackage.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from reigner.ingestion.loaders.base import LoadedDocument


class JsonLoader:
    """Reads ``.json`` or ``.jsonl`` files as bytes."""

    extensions: ClassVar[frozenset[str]] = frozenset({".json", ".jsonl"})

    def __init__(
        self,
        meta_extractor: Callable[[Path], dict[str, Any]] | None = None,
    ) -> None:
        self._meta_extractor = meta_extractor

    async def load(self, source: str | Path) -> LoadedDocument:
        """Read a JSON or JSONL file into bytes plus format metadata.

        Args:
            source: Path to the ``.json`` or ``.jsonl`` file.

        Returns:
            The raw bytes and metadata (format, size, JSONL line count).
        """
        path = Path(source)
        raw = await asyncio.to_thread(path.read_bytes)
        is_jsonl = path.suffix.lower() == ".jsonl"
        meta: dict[str, Any] = {
            "source": str(path),
            "filename": path.name,
            "size_bytes": len(raw),
            "content_type": "application/x-jsonlines" if is_jsonl else "application/json",
            "format": "jsonl" if is_jsonl else "json",
        }
        if is_jsonl:
            meta["line_count"] = sum(1 for line in raw.splitlines() if line.strip())
        if self._meta_extractor is not None:
            meta.update(self._meta_extractor(path))
        return LoadedDocument(raw=raw, meta=meta)
