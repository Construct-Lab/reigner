"""Ingestion pipeline — wired by ``reigner ingest``.

Bare ``reigner ingest`` resolves ``extractors.pipeline:pipeline`` against the
project root. Each PDF in ``library/raw/`` is loaded, compiled by MyExtractor
into verbatim ``body/*`` text plus a summary, then written as artifacts and
indexed for BM25.

See SPEC.md §8 for the full ingestion contract.
"""

from reigner.artifacts import ArtifactSchema
from reigner.ingestion import IngestionPipeline
from reigner.ingestion.loaders import PdfLoader
from reigner.ingestion.writers import ArtifactWriter, Bm25IndexWriter

from .my_extractor import MyExtractor, derive_identifiers

_schema = ArtifactSchema.from_yaml("schema.yaml")

pipeline = IngestionPipeline(
    loaders=[PdfLoader()],
    transforms=[MyExtractor()],  # schema is a class attr — do NOT pass schema=
    writers=[
        ArtifactWriter(root="library/artifacts", schema=_schema),
        Bm25IndexWriter(path="search-index/documents.json"),
    ],
    # entity_path is {course_module}/{topic_id}; PdfLoader doesn't supply these,
    # so derive them from the filename — same function the extractor uses.
    identifiers_fn=lambda loaded: derive_identifiers(loaded.meta["filename"]),
    concurrency=3,
    on_error="dead_letter",
    dead_letter_path="library/_dead_letter/",
)
