"""ExtractionResult and the error taxonomy ingestion deals in.

Four error types form a hierarchy under :class:`ExtractionError`:

* :class:`TransientError` — retried by the pipeline (rate limits, 5xx, network).
* :class:`ValidationError` — the model produced output that doesn't fit the
  schema; the malformed payload is preserved on ``.payload`` for dead-letter
  inspection.
* :class:`InputOverflowError` — input handed to a single-shot ``call_model``
  exceeded the configured ceiling and ``overflow_mode="error"`` refused it.
* :class:`ExtractionError` (raised directly) — every other permanent failure
  (unparseable JSON, prompt errors, runtime exceptions in user ``extract()``).

The pipeline catches :class:`ExtractionError` as the umbrella; users can catch
the subclasses for finer routing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(kw_only=True)
class ExtractionResult:
    """Output of one :meth:`LLMExtractor.run` call.

    ``sections`` and ``json_artifacts`` are passed verbatim to
    :meth:`reigner.artifacts.ArtifactWriter.write_entity`. ``meta`` is
    populated by :meth:`LLMExtractor.run` with provenance (source/prompt
    hashes, schema version, model id, token counts, cost) and ends up in
    ``extraction_meta.json``. Subclass ``extract()`` may pre-populate ``meta``
    with extra fields; the run wrapper merges its own keys on top.
    """

    sections: dict[str, str] = field(default_factory=dict)
    json_artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


class ExtractionError(Exception):
    """Permanent failure during extraction. Pipeline routes to dead-letter."""


class TransientError(ExtractionError):
    """Retryable failure that survived the extractor's own retry budget.

    Adapters raise :class:`reigner.harness.adapters.TransientAdapterError` for
    individual transient failures; :meth:`LLMExtractor.call_model` retries
    those internally and only re-raises as ``TransientError`` once retries are
    exhausted. The pipeline decides whether to retry the whole document later
    (network outage, sustained rate limit) or dead-letter it.
    """


class InputOverflowError(ExtractionError):
    """Single-shot input exceeded the ceiling and ``overflow_mode="error"``.

    Raised by :meth:`LLMExtractor.call_model` when ``len(input_text)`` is over
    ``max_input_chars`` and the extractor is configured to refuse rather than
    warn or truncate. Gets its own catchable type — distinct from unparseable
    JSON or schema failures — so callers can route an oversized document to
    :class:`MapReduceExtractor` instead of dead-lettering it. The pipeline still
    catches it under the :class:`ExtractionError` umbrella.
    """


class ValidationError(ExtractionError):
    """Model output failed schema validation.

    ``payload`` carries the parsed-but-invalid extraction so a dead-letter
    consumer can inspect what the model produced without re-running the call.
    """

    def __init__(self, message: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.payload = payload
