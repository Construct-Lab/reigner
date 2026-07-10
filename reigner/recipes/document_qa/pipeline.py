"""Ingestion pipeline for the document_qa recipe — wired by ``reigner ingest``.

Bare ``reigner ingest`` resolves ``extractors.pipeline:pipeline`` against the
project root. Each document in ``library/raw/`` is loaded, compiled by
``MyExtractor`` into ``document_summary`` / ``sections/*`` / ``insights/*`` plus
``metadata.json``, then written as artifacts and indexed for BM25.

Unlike the blank stub, this is already wired for the recipe's ``schema.yaml``
(``entity_path: "{entity_id}/{version}"``). The one line to make your own is
``derive_identifiers`` — it decides how a raw file becomes an entity name.
"""

from pathlib import Path
from typing import Any

from reigner.artifacts import ArtifactSchema
from reigner.ingestion import IngestionPipeline
from reigner.ingestion.loaders import MdLoader, PdfLoader
from reigner.ingestion.writers import ArtifactWriter, Bm25IndexWriter

from .my_extractor import MyExtractor

_schema = ArtifactSchema.from_yaml("schema.yaml")


def derive_identifiers(loaded: Any) -> dict[str, str]:
    """Map a loaded document to the ``entity_path`` placeholders.

    ``schema.yaml`` declares ``entity_path: "{entity_id}/{version}"``, so this
    must return both keys. The default names each entity by its filename slug at
    version ``v1`` — good enough to ingest immediately. Change this to match how
    *your* corpus identifies documents (e.g. a ticker + fiscal year parsed from
    the filename, or a field your loader's ``meta_extractor`` put on ``meta``).
    Keep it deterministic so re-ingesting the same file overwrites in place.
    """
    stem = Path(loaded.meta["filename"]).stem.lower()
    entity_id = "".join(c if c.isalnum() else "-" for c in stem).strip("-") or "unknown"
    return {"entity_id": entity_id, "version": "v1"}


pipeline = IngestionPipeline(
    loaders=[PdfLoader(), MdLoader()],
    transforms=[MyExtractor()],  # schema is a class attr — do NOT pass schema=
    writers=[
        ArtifactWriter(root="library/artifacts", schema=_schema),
        Bm25IndexWriter(path="search-index/documents.json"),
    ],
    identifiers_fn=derive_identifiers,
    concurrency=4,
    on_error="skip",
)
