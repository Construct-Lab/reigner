"""HTML loader.

Reads ``.html`` / ``.htm`` files into raw bytes. Tag-stripping and text
extraction are the extractor's job; leaving the bytes untouched lets
domain extractors choose their own parser (readability, table handling,
boilerplate removal, etc.).

This is the on-disk counterpart to ``UrlLoader``, which fetches HTML over
http(s). Use it for a committed corpus snapshot (e.g. SEC filings saved to
disk) where reproducibility matters more than a live fetch.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from reigner.ingestion.loaders.base import LoadedDocument


class HtmlLoader:
    """Reads an HTML file into bytes.

    Pass ``meta_extractor`` to derive domain metadata from the path
    (e.g. parse ``AAPL_10K_2024.html`` into ticker/year/form_type). The
    returned dict is merged into :attr:`LoadedDocument.meta`; keys it
    sets win over the loader's own keys.
    """

    extensions: ClassVar[frozenset[str]] = frozenset({".html", ".htm"})

    def __init__(
        self,
        meta_extractor: Callable[[Path], dict[str, Any]] | None = None,
    ) -> None:
        self._meta_extractor = meta_extractor

    async def load(self, source: str | Path) -> LoadedDocument:
        """Read an HTML file into raw bytes (decoding is the extractor's job).

        Args:
            source: Path to the ``.html`` / ``.htm`` file.

        Returns:
            The raw HTML bytes and basic file metadata.
        """
        path = Path(source)
        raw = await asyncio.to_thread(path.read_bytes)
        meta: dict[str, Any] = {
            "source": str(path),
            "filename": path.name,
            "size_bytes": len(raw),
            "content_type": "text/html",
        }
        if self._meta_extractor is not None:
            meta.update(self._meta_extractor(path))
        return LoadedDocument(raw=raw, meta=meta)
