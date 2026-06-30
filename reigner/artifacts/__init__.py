"""Artifact system — schema, writer, manifest, and conventions.

This package owns the write side and the schema contract; the read-side
``ArtifactStore`` lives in ``reigner.tools.artifacts``.
"""

from reigner.artifacts.manifest import ExtractionMeta
from reigner.artifacts.schema import ArtifactSchema, JsonArtifactSpec, SectionSpec
from reigner.artifacts.writer import (
    ArtifactWriteError,
    ArtifactWriter,
    SchemaValidationError,
)

__all__ = [
    "ArtifactSchema",
    "ArtifactWriteError",
    "ArtifactWriter",
    "ExtractionMeta",
    "JsonArtifactSpec",
    "SchemaValidationError",
    "SectionSpec",
]
