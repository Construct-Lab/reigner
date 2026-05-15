"""Ingestion — pipeline, extractor, loaders, writers.

T-14 lands the LLMExtractor base class and the ingestion error taxonomy.
T-15 lands the document loaders. The pipeline (T-16) and ingestion-side
writers ship in their own tasks and re-export from here as they land.
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
from reigner.ingestion.results import (
    ExtractionError,
    ExtractionResult,
    TransientError,
    ValidationError,
)

__all__ = [
    "ExtractionError",
    "ExtractionResult",
    "JsonLoader",
    "LLMExtractor",
    "LoadedDocument",
    "Loader",
    "MdLoader",
    "PdfLoader",
    "TransientError",
    "UrlLoader",
    "ValidationError",
    "resolve_adapter",
]
