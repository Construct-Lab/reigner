"""Ingestion — pipeline, extractor, loaders, writers.

Compiles raw documents into artifacts: loaders read sources, the extractor
turns them into structured output, and the pipeline fans each result out to
the artifact and index writers.
"""

from reigner.ingestion.extractor import (
    LLMExtractor,
    MapReduceExtractor,
    resolve_adapter,
)
from reigner.ingestion.loaders import (
    HtmlLoader,
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
    InputOverflowError,
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
    "HtmlLoader",
    "IngestionReport",
    "InputOverflowError",
    "JsonLoader",
    "LLMExtractor",
    "LoadedDocument",
    "Loader",
    "MapReduceExtractor",
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
