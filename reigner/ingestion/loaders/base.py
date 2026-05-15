"""Loader protocol and shared types.

A :class:`Loader` reads one source (file or URL) into a
:class:`LoadedDocument` — raw bytes plus a metadata dict.

Loaders deliberately do nothing else. No LLM calls, no validation, no
retry, no concurrency. Those concerns belong upstream
(:class:`reigner.ingestion.LLMExtractor`, T-14) and downstream
(``IngestionPipeline``, T-16, which routes sources to loaders by
extension or URL scheme and feeds each :class:`LoadedDocument` into
``LLMExtractor.extract(raw, meta)``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(kw_only=True)
class LoadedDocument:
    """One source rendered into raw bytes + metadata.

    ``raw`` is the unprocessed payload (PDF bytes, file bytes, response
    body). ``meta`` carries provenance the pipeline and extractor need
    (source path or URL, content-type, size, ...) plus any
    domain-specific fields a caller's ``meta_extractor`` hook adds.
    """

    raw: bytes
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Loader(Protocol):
    """Reads one source into a :class:`LoadedDocument`.

    Concrete loaders also expose either an ``extensions`` (file loaders)
    or ``schemes`` (URL loaders) class attribute that ``IngestionPipeline``
    uses for routing. Those aren't part of the protocol because file and
    URL loaders route differently.
    """

    async def load(self, source: str | Path) -> LoadedDocument: ...
