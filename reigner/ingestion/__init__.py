"""Ingestion — pipeline, extractor, loaders, writers.

T-14 lands the LLMExtractor base class and the ingestion error taxonomy.
The pipeline (T-16), loaders (T-15), and ingestion-side writers ship in
their own tasks and re-export from here as they land.
"""

from reigner.ingestion.extractor import LLMExtractor, resolve_adapter
from reigner.ingestion.results import (
    ExtractionError,
    ExtractionResult,
    TransientError,
    ValidationError,
)

__all__ = [
    "ExtractionError",
    "ExtractionResult",
    "LLMExtractor",
    "TransientError",
    "ValidationError",
    "resolve_adapter",
]
