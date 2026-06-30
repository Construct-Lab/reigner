"""PDF loader.

Reads ``.pdf`` files into raw bytes. Decoding to text is the extractor's
job (default: ``LLMExtractor.preprocess_pdf`` via ``pymupdf``); leaving
the bytes untouched lets domain extractors swap in OCR, table extraction,
multi-column handling, etc.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from reigner.ingestion.loaders.base import LoadedDocument


class PdfLoader:
    """Reads a PDF file into bytes.

    Pass ``meta_extractor`` to derive domain metadata from the path
    (e.g. parse ``AAPL_10K_2024.pdf`` into ticker/year/form_type). The
    returned dict is merged into :attr:`LoadedDocument.meta`; keys it
    sets win over the loader's own keys.
    """

    extensions: ClassVar[frozenset[str]] = frozenset({".pdf"})

    def __init__(
        self,
        meta_extractor: Callable[[Path], dict[str, Any]] | None = None,
    ) -> None:
        self._meta_extractor = meta_extractor

    async def load(self, source: str | Path) -> LoadedDocument:
        """Read a PDF file into raw bytes (decoding is the extractor's job).

        Args:
            source: Path to the ``.pdf`` file.

        Returns:
            The raw PDF bytes and basic file metadata.
        """
        path = Path(source)
        raw = await asyncio.to_thread(path.read_bytes)
        meta: dict[str, Any] = {
            "source": str(path),
            "filename": path.name,
            "size_bytes": len(raw),
            "content_type": "application/pdf",
        }
        if self._meta_extractor is not None:
            meta.update(self._meta_extractor(path))
        return LoadedDocument(raw=raw, meta=meta)
