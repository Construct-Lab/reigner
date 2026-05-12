"""LLMExtractor — base class for single-document extraction.

See SPEC.md §8.2 ("Layer B — LLMExtractor") and issue #14.

The base class owns everything that's the same regardless of domain: model
adapter wiring, retry on transient adapter errors, schema validation against
:class:`reigner.artifacts.ArtifactSchema`, deterministic idempotency keys,
token + cost accounting, and a default ``preprocess_pdf``. The subclass owns
``PROMPT`` and ``extract()`` — the irreducibly domain-specific parts.

The pipeline (T-16) calls :meth:`LLMExtractor.run` per document. ``run``
calls the user's ``extract``, validates the result against ``schema``, and
returns an :class:`ExtractionResult` whose ``meta`` is ready to be handed to
:meth:`reigner.artifacts.ArtifactWriter.write_entity` as the ``meta=`` arg.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from reigner.artifacts import ArtifactSchema
from reigner.harness.adapters import (
    AdapterError,
    ModelAdapter,
    TransientAdapterError,
)
from reigner.harness.adapters.base import TokenUsage
from reigner.harness.state import Prompt, Turn
from reigner.ingestion.results import (
    ExtractionError,
    ExtractionResult,
    TransientError,
    ValidationError,
)

# ---------------------------------------------------------------------------
# Adapter resolution from "provider:model_id" strings
# ---------------------------------------------------------------------------


def resolve_adapter(model_str: str) -> ModelAdapter:
    """Construct an adapter from a ``"provider:model_id"`` string.

    Users who need to pass api keys or other config should construct the
    adapter directly and pass it to ``LLMExtractor(adapter=...)``; this
    helper is the convenience path for the common case.
    """
    if ":" not in model_str:
        raise ValueError(
            f"model {model_str!r} must be of the form 'provider:model_id' "
            "(e.g. 'anthropic:claude-opus-4-7'). Supported providers: "
            "anthropic, openai, gemini."
        )
    provider, model_id = model_str.split(":", 1)
    provider = provider.strip().lower()
    model_id = model_id.strip()

    if provider == "anthropic":
        from reigner.harness.adapters.anthropic import AnthropicAdapter

        return AnthropicAdapter(model=model_id)
    if provider == "openai":
        from reigner.harness.adapters.openai import OpenAIAdapter

        return OpenAIAdapter(model=model_id)
    if provider == "gemini":
        from reigner.harness.adapters.gemini import GeminiAdapter

        return GeminiAdapter(model=model_id)
    raise ValueError(
        f"unknown provider {provider!r} in model={model_str!r}. "
        "Supported providers: anthropic, openai, gemini."
    )


# ---------------------------------------------------------------------------
# JSON parsing — strip a markdown code fence if the model wrapped its output.
# ---------------------------------------------------------------------------


_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n(?P<body>.*?)\n```\s*$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    m = _FENCE_RE.match(text)
    return m.group("body") if m else text


# ---------------------------------------------------------------------------
# LLMExtractor
# ---------------------------------------------------------------------------


class LLMExtractor(ABC):
    """Subclass to define a domain-specific extractor.

    Class attributes the subclass must (or may) set:

    * ``schema`` — the :class:`ArtifactSchema` the output is validated against.
    * ``model`` — ``"provider:model_id"`` resolved by :func:`resolve_adapter`,
      or pass an adapter instance to ``__init__`` to override.
    * ``PROMPT`` — the system prompt template. Free-form; the subclass
      ``extract()`` decides how (and whether) to format it.
    * ``max_retries`` (default 2) — transient retries inside one ``run``.
    * ``base_backoff_seconds`` (default 1.0) — exponential backoff base.
    * ``pricing`` — optional ``{model_full_id: {"input": $/Mtok,
      "output": $/Mtok}}``. None ⇒ ``cost_usd`` is reported as 0.0.

    The subclass implements :meth:`extract`. Inside ``extract`` it can call:

    * :meth:`call_model` — single-shot JSON request; raises
      :class:`TransientError` after retries, :class:`ExtractionError` on
      unparseable response.
    * :meth:`preprocess_pdf` — default ``pymupdf`` text extraction; override
      for OCR or multi-column handling.
    """

    schema: ClassVar[ArtifactSchema]
    model: ClassVar[str] = ""
    PROMPT: ClassVar[str] = ""
    max_retries: ClassVar[int] = 2
    base_backoff_seconds: ClassVar[float] = 1.0
    pricing: ClassVar[dict[str, dict[str, float]] | None] = None

    def __init__(self, adapter: ModelAdapter | None = None) -> None:
        if adapter is not None:
            self._adapter: ModelAdapter = adapter
        else:
            if not self.model:
                raise ValueError(
                    f"{type(self).__name__}: set `model` class attribute or pass "
                    "an adapter to __init__()"
                )
            self._adapter = resolve_adapter(self.model)
        # Token usage accumulated across all model calls in the current run.
        self._run_usage = TokenUsage.empty()

    # ---- Public API ---------------------------------------------------------

    @property
    def adapter(self) -> ModelAdapter:
        return self._adapter

    async def run(self, raw: bytes, meta: dict[str, Any]) -> ExtractionResult:
        """Orchestrate one extraction end-to-end.

        Calls the user's :meth:`extract`, validates the returned
        :class:`ExtractionResult` against ``self.schema``, and stamps the
        result's ``meta`` with provenance fields used by the writer's
        manifest. Token usage is accumulated across any retries inside
        :meth:`call_model`.

        Raises :class:`ExtractionError` (or its subclasses) on failure — never
        partial results.
        """
        self._run_usage = TokenUsage.empty()
        result = await self.extract(raw, meta)
        self._validate_against_schema(result)

        provenance: dict[str, Any] = {
            "source_hash": self._source_hash(raw),
            "prompt_hash": self._prompt_hash(),
            "schema_version": self.schema.version,
            "model": f"{self._adapter.name}:{self._adapter.model}",
            "tokens_in": self._run_usage.prompt,
            "tokens_out": self._run_usage.completion,
            "cost_usd": self._compute_cost(self._run_usage),
        }
        # Subclass-supplied meta wins on conflicts; provenance fills in the rest.
        merged = {**provenance, **result.meta}
        result.meta = merged
        return result

    def cache_key(self, raw: bytes) -> str:
        """``source_hash:schema_version:prompt_hash`` — deterministic.

        T-16 (pipeline) compares this against the ``extractor`` block in the
        existing ``extraction_meta.json`` to decide whether to skip a source
        that's already been ingested with the same prompt + schema.
        """
        return f"{self._source_hash(raw)}:{self.schema.version}:{self._prompt_hash()}"

    # ---- Subclass implements ------------------------------------------------

    @abstractmethod
    async def extract(self, raw: bytes, meta: dict[str, Any]) -> ExtractionResult: ...

    # ---- Subclass uses ------------------------------------------------------

    async def call_model(self, prompt: str, input_text: str) -> dict[str, Any]:
        """Single-shot call expecting a JSON object back.

        Wraps the harness adapter in degenerate "no tools, single user turn"
        mode. Retries on :class:`TransientAdapterError` with exponential
        backoff up to ``self.max_retries`` additional attempts.

        Raises:
            TransientError: after retries exhausted on a transient adapter
                error.
            ExtractionError: on any non-transient adapter error or when the
                model's response isn't a JSON object.
        """
        adapter_prompt = Prompt(
            stable=prompt,
            dynamic_context={},
            messages=[Turn(role="user", content=input_text)],
        )

        last_transient: TransientAdapterError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                action = await self._adapter.call(adapter_prompt, [])
            except TransientAdapterError as exc:
                last_transient = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(self.base_backoff_seconds * (2**attempt))
                    continue
                raise TransientError(
                    f"transient adapter error after {self.max_retries + 1} attempts: {exc}"
                ) from exc
            except AdapterError as exc:
                raise ExtractionError(f"adapter error: {exc}") from exc

            self._run_usage = _add_usage(self._run_usage, action.usage)
            return self._parse_json_response(action.text or "")

        # Loop exits only via return/raise; this is unreachable but keeps mypy
        # convinced about the return type.
        raise TransientError(f"transient adapter error (unreachable); last error: {last_transient}")

    async def preprocess_pdf(self, raw: bytes) -> str:
        """Default PDF → text using pymupdf.

        Pages are joined by form-feed (``\\f``) so downstream consumers can
        recover page boundaries. Override for OCR, multi-column layouts, or
        scanned documents — see SPEC §8.2 + §8.5 on the OCR boundary.
        """
        try:
            import pymupdf  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "preprocess_pdf needs pymupdf. Install with "
                "`uv add reigner[ingestion]` (or `pip install reigner[ingestion]`), "
                "or override preprocess_pdf in your subclass."
            ) from exc

        doc = pymupdf.open(stream=raw, filetype="pdf")
        try:
            return "\f".join(page.get_text() for page in doc)
        finally:
            doc.close()

    # ---- Internals ----------------------------------------------------------

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        body = _strip_code_fence(text.strip())
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ExtractionError(
                f"model response was not valid JSON: {exc.msg} (first 200 chars: {body[:200]!r})"
            ) from exc
        if not isinstance(parsed, dict):
            raise ExtractionError(
                f"model response must be a JSON object, got {type(parsed).__name__}"
            )
        return parsed

    def _validate_against_schema(self, result: ExtractionResult) -> None:
        # Required sections present.
        for required in self.schema.required_sections():
            if required.name not in result.sections:
                raise ValidationError(
                    f"missing required section {required.name!r}",
                    payload=_payload_snapshot(result),
                )

        # Required JSON artifacts + field-level checks.
        for spec in self.schema.json_artifacts:
            if spec.name not in result.json_artifacts:
                if spec.required_field_names:
                    raise ValidationError(
                        f"missing required JSON artifact {spec.name!r}",
                        payload=_payload_snapshot(result),
                    )
                continue
            payload = result.json_artifacts[spec.name]
            if not isinstance(payload, dict):
                raise ValidationError(
                    f"json_artifact {spec.name!r} must be a dict, got {type(payload).__name__}",
                    payload=_payload_snapshot(result),
                )
            missing = spec.required_field_names - set(payload)
            if missing:
                raise ValidationError(
                    f"json_artifact {spec.name!r} missing required fields: {sorted(missing)}",
                    payload=_payload_snapshot(result),
                )
            for field_name, expected_type in spec.fields.items():
                if field_name not in payload:
                    continue
                value = payload[field_name]
                if value is None:
                    continue
                if not isinstance(value, expected_type):
                    raise ValidationError(
                        f"json_artifact {spec.name!r} field {field_name!r}: "
                        f"expected {expected_type.__name__}, got "
                        f"{type(value).__name__}",
                        payload=_payload_snapshot(result),
                    )

    def _source_hash(self, raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    def _prompt_hash(self) -> str:
        return hashlib.sha256(self.PROMPT.encode("utf-8")).hexdigest()

    def _compute_cost(self, usage: TokenUsage) -> float:
        if not self.pricing:
            return 0.0
        key = f"{self._adapter.name}:{self._adapter.model}"
        rates = self.pricing.get(key)
        if rates is None:
            return 0.0
        return (
            rates.get("input", 0.0) * usage.prompt / 1_000_000.0
            + rates.get("output", 0.0) * usage.completion / 1_000_000.0
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_usage(a: TokenUsage, b: TokenUsage) -> TokenUsage:
    return TokenUsage(
        prompt=a.prompt + b.prompt,
        completion=a.completion + b.completion,
        cached=a.cached + b.cached,
        total=a.total + b.total,
    )


def _payload_snapshot(result: ExtractionResult) -> dict[str, Any]:
    """Shallow copy of the result's user-facing data for ValidationError."""
    return {
        "sections": dict(result.sections),
        "json_artifacts": dict(result.json_artifacts),
    }
