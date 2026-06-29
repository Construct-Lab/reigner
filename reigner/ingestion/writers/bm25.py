r"""Bm25IndexWriter — JSON-sidecar dump consumed by Bm25Index.

Each entry has the shape::

    {
      "id":          "<sorted-identifier-values joined by '/'>",
      "identifiers": {"<key>": "<value>", ...},
      "text":        "<all sections concatenated by \\n\\n>",
      "sections":    {"<section-name>": "<section-text>", ...},
      "source":      "<raw source path or URL>",
    }

``text`` powers ``bm25_search`` (whole-document scoring); ``sections`` powers
``section_search`` (per-section scoring). Both fields are populated by the
writer so the reader can ship without re-deriving section boundaries.

Writes are atomic (write-to-tmp then ``Path.replace``) and concurrency-safe
via an asyncio lock — multiple pipeline workers can update the same sidecar
from one event loop without losing entries.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from reigner.ingestion.loaders import LoadedDocument
from reigner.ingestion.results import ExtractionResult


class Bm25IndexWriter:
    """Pipeline writer that upserts entities into a bm25 JSON sidecar."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()

    async def write(
        self,
        *,
        loaded: LoadedDocument,
        result: ExtractionResult,
        identifiers: dict[str, str],
    ) -> None:
        """Upsert the entity's searchable entry into the sidecar atomically.

        Args:
            loaded: The source document, used for provenance (source/url).
            result: The extraction whose sections become searchable text.
            identifiers: Entity identity fields, joined to form the entry id.
        """
        entry = _build_entry(loaded, result, identifiers)
        async with self._lock:
            await asyncio.to_thread(self._upsert, entry)

    def _upsert(self, entry: dict[str, Any]) -> None:
        existing = self._read_existing()
        existing = [e for e in existing if e.get("id") != entry["id"]]
        existing.append(entry)
        existing.sort(key=lambda e: e.get("id", ""))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(existing, indent=2, sort_keys=True))
        tmp.replace(self.path)

    def _read_existing(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []


def _build_entry(
    loaded: LoadedDocument,
    result: ExtractionResult,
    identifiers: dict[str, str],
) -> dict[str, Any]:
    entity_id = "/".join(identifiers[k] for k in sorted(identifiers)) if identifiers else ""
    text = "\n\n".join(result.sections.values())
    source = loaded.meta.get("source") or loaded.meta.get("url") or ""
    return {
        "id": entity_id,
        "identifiers": dict(identifiers),
        "text": text,
        "sections": dict(result.sections),
        "source": str(source),
    }
