"""Ingestion-side writer surface (SPEC §8.3, issue #16).

Re-exports :class:`reigner.artifacts.ArtifactWriter` so callers can write
``from reigner.ingestion.writers import ArtifactWriter, Bm25IndexWriter`` as
the SPEC example does.
"""

from reigner.artifacts import ArtifactWriter
from reigner.ingestion.writers.base import (
    IngestionReport,
    PipelineWriter,
    SourceFailure,
    Transform,
)
from reigner.ingestion.writers.bm25 import Bm25IndexWriter

__all__ = [
    "ArtifactWriter",
    "Bm25IndexWriter",
    "IngestionReport",
    "PipelineWriter",
    "SourceFailure",
    "Transform",
]
