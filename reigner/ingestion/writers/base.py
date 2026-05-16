"""Pipeline writer + transform protocols and the final-report dataclasses.

See SPEC.md §8.3 ("Layer C — IngestionPipeline") and issue #16.

The pipeline (T-16) fans each successful extraction out to a list of writers.
Two writer shapes are supported:

* :class:`reigner.artifacts.ArtifactWriter` — the canonical entity store, kept
  on its existing ``write_entity(**identifiers, sections=..., json_artifacts=...,
  meta=...)`` signature and dispatched by ``isinstance`` inside the pipeline.
* Any object satisfying :class:`PipelineWriter` — a uniform async
  ``write(loaded=, result=, identifiers=)`` surface used by everything else
  (e.g. :class:`reigner.ingestion.writers.Bm25IndexWriter`).

:class:`Transform` is the contract a single pipeline step must satisfy.
:class:`reigner.ingestion.LLMExtractor` already does. v0 only runs one
transform per pipeline; the protocol exists so non-LLM transforms (SPEC §8.4)
can slot in later without touching the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from reigner.ingestion.loaders import LoadedDocument
from reigner.ingestion.results import ExtractionResult


@runtime_checkable
class PipelineWriter(Protocol):
    """Uniform async writer the pipeline calls for non-ArtifactWriter sinks."""

    async def write(
        self,
        *,
        loaded: LoadedDocument,
        result: ExtractionResult,
        identifiers: dict[str, str],
    ) -> None: ...


@runtime_checkable
class Transform(Protocol):
    """A single pipeline step turning raw bytes into an :class:`ExtractionResult`.

    ``cache_key`` is consulted for directory-level idempotency: a source whose
    key matches the on-disk ``extraction_meta.json`` is skipped. Transforms
    that genuinely cannot be cached should return a unique key per call.
    """

    async def run(self, raw: bytes, meta: dict[str, Any]) -> ExtractionResult: ...

    def cache_key(self, raw: bytes) -> str: ...


@dataclass(kw_only=True)
class SourceFailure:
    """One source's failure as recorded on :class:`IngestionReport`."""

    source: str
    error_type: str
    message: str
    dead_letter_path: Path | None = None


@dataclass(kw_only=True)
class IngestionReport:
    """Aggregate outcome of one :meth:`IngestionPipeline.run` call (SPEC §8.3)."""

    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    wall_clock_seconds: float = 0.0
    failures: list[SourceFailure] = field(default_factory=list)
    dead_lettered: list[Path] = field(default_factory=list)
