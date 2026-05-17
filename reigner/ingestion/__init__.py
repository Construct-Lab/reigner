"""Ingestion — pipeline, extractor, loaders, writers.

T-14 lands the LLMExtractor base class and the ingestion error taxonomy.
T-15 lands the document loaders. T-16 lands the IngestionPipeline runner
and the ingestion-side writers (ArtifactWriter re-export + Bm25IndexWriter).
"""

from reigner.ingestion.extractor import LLMExtractor, resolve_adapter
from reigner.ingestion.loaders import (
    JsonLoader,
    LoadedDocument,
    Loader,
    MdLoader,
    PdfLoader,
    UrlLoader,
)
from reigner.ingestion.pipeline import IngestionPipeline
from reigner.ingestion.results import (
    ExtractionError,
    ExtractionResult,
    TransientError,
    ValidationError,
)
from reigner.ingestion.writers import (
    ArtifactWriter,
    Bm25IndexWriter,
    IngestionReport,
    PipelineWriter,
    SourceFailure,
    Transform,
)

__all__ = [
    "ArtifactWriter",
    "Bm25IndexWriter",
    "ExtractionError",
    "ExtractionResult",
    "IngestionPipeline",
    "IngestionReport",
    "JsonLoader",
    "LLMExtractor",
    "LoadedDocument",
    "Loader",
    "MdLoader",
    "PdfLoader",
    "PipelineWriter",
    "SourceFailure",
    "TransientError",
    "Transform",
    "UrlLoader",
    "ValidationError",
    "resolve_adapter",
]
