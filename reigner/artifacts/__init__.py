"""Artifact system — schema, writer, manifest, and conventions.

See SPEC.md §7 and §8.1. T-13 lands the write side and the contract; the
read-side ``ArtifactStore`` lives in ``reigner.tools.artifacts`` (T-09).
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
