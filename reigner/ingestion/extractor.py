"""LLMExtractor — base class for single-document extraction.

The base class owns everything that's the same regardless of domain: model
adapter wiring, retry on transient adapter errors, schema validation against
:class:`reigner.artifacts.ArtifactSchema`, deterministic idempotency keys,
token + cost accounting, and a default ``preprocess_pdf``. The subclass owns
``PROMPT`` and ``extract()`` — the irreducibly domain-specific parts.

The pipeline calls :meth:`LLMExtractor.run` per document. ``run`` calls the
user's ``extract``, validates the result against ``schema``, and
returns an :class:`ExtractionResult` whose ``meta`` is ready to be handed to
:meth:`reigner.artifacts.ArtifactWriter.write_entity` as the ``meta=`` arg.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import warnings
from abc import ABC, abstractmethod
from collections import defaultdict
from contextvars import ContextVar
from pathlib import Path
from typing import Any, ClassVar, Literal, cast

from reigner.artifacts import ArtifactSchema
from reigner.harness.adapters import (
    AdapterError,
    ModelAdapter,
    TransientAdapterError,
    build_adapter,
)
from reigner.harness.adapters.base import TokenUsage
from reigner.harness.state import Prompt, Turn
from reigner.ingestion.results import (
    ExtractionError,
    ExtractionResult,
    InputOverflowError,
    TransientError,
    ValidationError,
)
from reigner.pricing import cost_usd
from reigner.types import ConfigError, ProviderName

# ---------------------------------------------------------------------------
# Adapter resolution from "provider:model_id" strings
# ---------------------------------------------------------------------------


def resolve_adapter(model_str: str) -> ModelAdapter:
    """Construct an adapter from a ``"provider:model_id"`` string.

    A thin string-parsing convenience over
    :func:`reigner.harness.adapters.build_adapter`: it splits the shorthand and
    delegates construction (and error handling) to the canonical builder. Users
    who need to pass api keys or other config should construct the adapter
    directly and pass it to ``LLMExtractor(adapter=...)``.
    """
    if ":" not in model_str:
        raise ConfigError(
            f"model {model_str!r} must be of the form 'provider:model_id' "
            "(e.g. 'anthropic:claude-opus-4-7')."
        )
    provider, model_id = model_str.split(":", 1)
    # ``build_adapter`` enforces ProviderName at runtime via its fall-through, so
    # an unknown provider here still raises ConfigError — the cast only silences
    # the static checker on the raw split string.
    return build_adapter(cast(ProviderName, provider.strip().lower()), model_id.strip())


# ---------------------------------------------------------------------------
# JSON parsing — strip a markdown code fence if the model wrapped its output.
# ---------------------------------------------------------------------------


_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n(?P<body>.*?)\n```\s*$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    m = _FENCE_RE.match(text)
    return m.group("body") if m else text


# ---------------------------------------------------------------------------
# Per-run token accounting
# ---------------------------------------------------------------------------


class _UsageAccumulator:
    """Mutable per-run token tally, held in a :class:`ContextVar`.

    One extractor instance is shared across documents by the pipeline, which
    runs each document in its own task. Keeping the tally on the instance let a
    second document's ``run()`` reset it mid-flight and corrupt the first's
    totals. This object lives in the context instead, so each ``run()`` gets its
    own tally.

    It is mutated *in place* (via :meth:`add`) and never rebound in the
    ContextVar. That matters for fan-out: ``asyncio.gather`` child tasks run in a
    *copy* of the context but share this same object, so in-place additions stay
    visible to the parent ``run()``. Rebinding the ContextVar inside a child
    task would only touch the child's copy. The read-modify-write in
    :meth:`add` has no ``await``, so under single-thread asyncio it is atomic
    across coroutines and cannot lose updates.
    """

    __slots__ = ("usage",)

    def __init__(self) -> None:
        self.usage: TokenUsage = TokenUsage.empty()

    def add(self, delta: TokenUsage) -> None:
        self.usage = _add_usage(self.usage, delta)


# None default ⇒ a call_model outside any run() simply doesn't accumulate
# (nothing is reading the tally in that case), rather than raising.
_run_usage: ContextVar[_UsageAccumulator | None] = ContextVar(
    "reigner_ingest_run_usage", default=None
)


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
    * ``max_input_chars`` (default 200_000) — single-shot input ceiling; see
      :meth:`call_model`. Set to ``None`` to disable the overflow guard.
    * ``overflow_mode`` (default ``"warn"``) — what the guard does on overflow.
    * ``pricing`` — optional per-extractor rate override,
      ``{"provider:model_id": {"input": $/Mtok, "output": $/Mtok}}``. Unset (or
      no entry for the active model) ⇒ cost falls back to
      :func:`reigner.pricing.cost_usd`, the same origin table chat/eval price
      from, so ``cost_usd`` is only 0.0 when that table also lacks the model.

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
    # Single-shot input ceiling (chars, not tokens — adapters expose no
    # context-window estimate; see harness/adapters/base.py). None disables the
    # guard, which is exactly how MapReduceExtractor opts out.
    max_input_chars: ClassVar[int | None] = 200_000
    overflow_mode: ClassVar[Literal["warn", "error", "truncate"]] = "warn"

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

    # ---- Public API ---------------------------------------------------------

    @property
    def adapter(self) -> ModelAdapter:
        """The resolved model adapter backing this extractor's calls."""
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
        # Per-run tally in the context, not on the instance: the pipeline shares
        # one extractor across documents, and each run() must count only its own
        # model calls (see _UsageAccumulator).
        acc = _UsageAccumulator()
        token = _run_usage.set(acc)
        try:
            result = await self.extract(raw, meta)
        finally:
            _run_usage.reset(token)
        self._validate_against_schema(result)

        provenance: dict[str, Any] = {
            "source_hash": self._source_hash(raw),
            "prompt_hash": self._prompt_hash(),
            "schema_version": self.schema.version,
            "model": f"{self._adapter.name}:{self._adapter.model}",
            "tokens_in": acc.usage.prompt,
            "tokens_out": acc.usage.completion,
            "cost_usd": self._compute_cost(acc.usage),
        }
        # Subclass-supplied meta wins on conflicts; provenance fills in the rest.
        merged = {**provenance, **result.meta}
        result.meta = merged
        return result

    def cache_key(self, raw: bytes) -> str:
        """``source_hash:schema_version:prompt_hash`` — deterministic.

        The pipeline compares this against the ``extractor`` block in the
        existing ``extraction_meta.json`` to decide whether to skip a source
        that's already been ingested with the same prompt + schema.

        Args:
            raw: The raw source bytes to key.

        Returns:
            A deterministic cache key for idempotency checks.
        """
        return f"{self._source_hash(raw)}:{self.schema.version}:{self._prompt_hash()}"

    # ---- Subclass implements ------------------------------------------------

    @abstractmethod
    async def extract(self, raw: bytes, meta: dict[str, Any]) -> ExtractionResult:
        """Produce an :class:`ExtractionResult` from one document.

        Args:
            raw: The raw source bytes for the document.
            meta: Loader-provided metadata (source, identifiers, …).

        Returns:
            The domain-specific sections and JSON artifacts for the entity.
        """
        ...

    # ---- Subclass uses ------------------------------------------------------

    async def call_model(self, prompt: str, input_text: str) -> dict[str, Any]:
        """Single-shot call expecting a JSON object back.

        This is **single-shot and does not chunk**: the entire ``input_text``
        goes in one request. For documents too large to read in one call,
        subclass :class:`MapReduceExtractor` — it chunks below the limit by
        design and so never trips the overflow guard.

        Before sending, :meth:`_guard_input_size` checks ``len(input_text)``
        against ``max_input_chars`` and, on overflow, acts per
        ``overflow_mode``: ``"warn"`` (default) shouts but sends the full text,
        ``"error"`` raises :class:`InputOverflowError`, ``"truncate"`` cuts the
        tail and says so. The point is to make a too-big single-shot call
        *loud* rather than let it silently lose the document tail.

        Wraps the harness adapter in degenerate "no tools, single user turn"
        mode. Retries on :class:`TransientAdapterError` with exponential
        backoff up to ``self.max_retries`` additional attempts.

        Raises:
            InputOverflowError: when input exceeds ``max_input_chars`` and
                ``overflow_mode="error"``.
            TransientError: after retries exhausted on a transient adapter
                error.
            ExtractionError: on any non-transient adapter error or when the
                model's response isn't a JSON object.
        """
        input_text = self._guard_input_size(input_text)
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

            acc = _run_usage.get()
            if acc is not None:
                acc.add(action.usage)
            return self._parse_json_response(action.text or "")

        # Loop exits only via return/raise; this is unreachable but keeps mypy
        # convinced about the return type.
        raise TransientError(f"transient adapter error (unreachable); last error: {last_transient}")

    async def preprocess_pdf(self, raw: bytes) -> str:
        r"""Default PDF → text using pymupdf.

        Pages are joined by form-feed (``\f``) so downstream consumers can
        recover page boundaries. Override for OCR, multi-column layouts, or
        scanned documents.

        Args:
            raw: The raw PDF bytes.

        Returns:
            The extracted text, with pages separated by form-feed characters.

        Raises:
            ImportError: If the optional ``pymupdf`` dependency is missing.
        """
        try:
            import pymupdf
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

    def _guard_input_size(self, input_text: str) -> str:
        """Loud overflow guard. Returns the text to actually send.

        Measures ``len(input_text)`` only (not the system prompt) against
        ``max_input_chars``. ``max_input_chars`` is a *proxy* threshold, not the
        model's real context window — so ``warn`` flags risk without claiming a
        drop happened; only ``truncate`` actually cuts the tail.

        * ``warn`` (default): :func:`warnings.warn`, returns the full text —
          never a silent drop.
        * ``error``: raises :class:`InputOverflowError`.
        * ``truncate``: cuts to ``max_input_chars`` and warns how much went.
        """
        cap = self.max_input_chars
        n = len(input_text)
        if cap is None or n <= cap:
            return input_text

        hint = "Use MapReduceExtractor for whole-document extraction."
        if self.overflow_mode == "error":
            raise InputOverflowError(
                f"call_model received {n:,} chars, over the {cap:,} ceiling "
                f"(overflow_mode='error'). {hint}"
            )
        if self.overflow_mode == "truncate":
            warnings.warn(
                f"call_model truncated input from {n:,} to {cap:,} chars "
                f"({n - cap:,} chars of the tail dropped). {hint}",
                stacklevel=2,
            )
            return input_text[:cap]
        # warn (default): shout, but send the whole thing.
        warnings.warn(
            f"call_model received {n:,} chars, over the {cap:,} ceiling. Sent in "
            f"full, but this may exceed the model's context window (the provider "
            f"will then reject or truncate it). {hint}",
            stacklevel=2,
        )
        return input_text

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
        # A per-extractor ``pricing`` override wins when it knows this model;
        # otherwise fall back to reigner.pricing, the single origin table
        # chat/eval already price from, so ingest cost works with no hand-written
        # rates. cost_usd returns None for a model it doesn't know -> report 0.0.
        if self.pricing:
            key = f"{self._adapter.name}:{self._adapter.model}"
            rates = self.pricing.get(key)
            if rates is not None:
                return (
                    rates.get("input", 0.0) * usage.prompt / 1_000_000.0
                    + rates.get("output", 0.0) * usage.completion / 1_000_000.0
                )
        return cost_usd(usage, self._adapter.model) or 0.0


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


# ---------------------------------------------------------------------------
# MapReduceExtractor
# ---------------------------------------------------------------------------


class _MapChunkSkipped(Exception):
    """Internal marker: a queued map chunk was skipped after a sibling errored.

    Raised inside the fan-out path (``map_concurrency > 1``) so a chunk that had
    not yet started when another failed is neither collected as a result nor
    re-raised as the run's error. Never escapes :meth:`MapReduceExtractor._map`.
    """


class MapReduceExtractor(LLMExtractor):
    """Whole-document extractor for sources too big for one model call.

    Subclass this instead of :class:`LLMExtractor` when a document must be read
    in full but doesn't fit in a single call. The base owns the domain-agnostic
    map-reduce machinery and implements :meth:`extract` itself as a template
    method — the subclass no longer writes ``extract``. The flow is::

        preprocess_pdf -> _chunk_pages -> _map -> reduce -> summarize
                       -> (enforce max_chars) -> post_process -> ExtractionResult

    What the subclass supplies:

    * ``MAP_PROMPT`` — formatted with ``{section_spec}`` (rendered from
      ``self.schema``) plus any keys from :meth:`prompt_context`. Each chunk is
      sent with this prompt; the model returns a JSON object mapping section
      name -> extracted content. Keys that aren't schema sections are dropped.
    * ``REDUCE_PROMPT`` — formatted with ``{section}``, ``{max_chars}``, plus
      :meth:`prompt_context` keys. The default per-section reduce calls the
      model with this and reads ``{"content": "..."}`` back.
    * :meth:`summarize` (optional) — a *cross-section* hook that runs after
      reduce to synthesize derived sections (e.g. a required overall summary)
      from the already-reduced sections. Default is a no-op. May stash derived
      non-section values (a title, say) into ``meta`` for :meth:`post_process`.
    * :meth:`post_process` (optional) — turns the final sections into JSON
      artifacts deterministically. Default returns ``{}``.

    Override seams with useful defaults:

    * :meth:`reduce` — the single method to override for a different reduce
      strategy (e.g. one whole-section-set pass) without touching chunk/map.
    * :meth:`prompt_context` — extra ``.format`` keys for the prompt templates.
    * ``MAP_EXCLUDE`` — section names left out of the rendered section spec
      because they're produced by :meth:`summarize`, not the map.

    Guarantees: every page is seen (a page larger than ``chunk_chars`` becomes
    its own over-budget chunk rather than being split or dropped), and every
    final section is hard-bounded to its schema ``max_chars``.

    Concurrency: map fan-out is bounded by ``map_concurrency`` (default 1 =
    sequential). With ``map_concurrency > 1`` chunks are mapped under an
    ``asyncio.Semaphore``, collected by chunk index then flattened, so output is
    byte-for-byte order-stable regardless of completion order. Token/cost
    accounting is concurrency-safe: the per-run tally lives in a context, not on
    the shared instance (see :class:`_UsageAccumulator`), and is mutated in place
    so additions survive ``asyncio.gather``'s context copy. Per-run context is
    threaded explicitly through ``meta`` rather than stored on ``self`` for the
    same shared-instance reason.
    """

    MAP_PROMPT: ClassVar[str] = ""
    REDUCE_PROMPT: ClassVar[str] = ""
    # Opt out of LLMExtractor's single-shot overflow guard: map-reduce already
    # chunks below the limit by design (``chunk_chars`` / ``reduce_input_chars``
    # bound every call_model call), so the guard would only ever false-alarm —
    # e.g. on an over-budget single page. The smoke alarm is for the single-shot
    # path it tells users to escape *to* this class from.
    max_input_chars: ClassVar[int | None] = None
    # Cap on the text sent to one map call; the document is processed in as many
    # of these windows as it takes.
    chunk_chars: ClassVar[int] = 100_000
    # Guard on the joined fragments handed to one reduce call.
    reduce_input_chars: ClassVar[int] = 80_000
    # Upper bound on in-flight map calls. 1 (default) is the sequential path,
    # byte-for-byte the pre-fan-out behavior including fail-fast on the first
    # chunk error. >1 fans chunks out under an asyncio.Semaphore. Validated >= 1.
    map_concurrency: ClassVar[int] = 1
    # Sections produced by summarize() rather than the map — omitted from the
    # rendered section spec so the model isn't asked to fill them per chunk.
    MAP_EXCLUDE: ClassVar[frozenset[str]] = frozenset()
    # Chunk-level map cache. None ⇒ the cache seams below are no-ops (always
    # miss), so behaviour is byte-for-byte unchanged. Point a subclass at a
    # directory (e.g. ``Path("./.reigner/ingest-cache")``) to turn on the
    # bundled on-disk JSON backend.
    map_cache_dir: ClassVar[Path | None] = None

    # ---- Template method (subclass does not override extract) ---------------

    async def extract(self, raw: bytes, meta: dict[str, Any]) -> ExtractionResult:
        """Map-reduce extraction: chunk, map per window, reduce, summarize.

        Args:
            raw: The raw document bytes (assumed PDF by default).
            meta: Loader-provided metadata.

        Returns:
            The assembled :class:`ExtractionResult` across all chunks.
        """
        full_text = await self.preprocess_pdf(raw)
        chunks = self._chunk_pages(full_text)
        fragments = await self._map(chunks, meta)
        sections = await self.reduce(fragments, meta)
        sections.update(await self.summarize(sections, meta))
        sections = self._enforce_max_chars(sections)
        json_artifacts = self.post_process(sections, meta)
        return ExtractionResult(sections=sections, json_artifacts=json_artifacts)

    # ---- Subclass seams -----------------------------------------------------

    def prompt_context(self, meta: dict[str, Any]) -> dict[str, Any]:
        """Extra ``.format`` keys for ``MAP_PROMPT`` / ``REDUCE_PROMPT``.

        Default is empty. Override to feed per-document context (e.g.
        ``{"filename": meta.get("filename", "unknown")}``).
        """
        return {}

    async def summarize(self, sections: dict[str, str], meta: dict[str, Any]) -> dict[str, str]:
        """Cross-section hook: derive new sections from the reduced ones.

        Runs after :meth:`reduce`. Returns a mapping of derived section name ->
        content that is merged into the result (e.g. a required overall summary
        synthesized from all the topical sections). Default is a no-op. May
        mutate ``meta`` to stash derived values (a title, say) that
        :meth:`post_process` then reads.
        """
        return {}

    def post_process(
        self, sections: dict[str, str], meta: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """Turn the final sections into JSON artifacts deterministically.

        Default returns ``{}``. Override to compute coverage flags, metadata,
        etc. from which sections got filled — no model guesswork.
        """
        return {}

    # ---- Overridable reduce (the single seam for a different strategy) ------

    async def reduce(
        self, fragments_by_section: dict[str, list[str]], meta: dict[str, Any]
    ) -> dict[str, str]:
        """Default reduce: loop per section, bounding each to its ``max_chars``.

        Override this one method (and nothing in chunk/map) for a different
        strategy — e.g. a single pass over the whole section set.
        """
        sections: dict[str, str] = {}
        for name, frags in fragments_by_section.items():
            sections[name] = await self._reduce_section(name, frags, meta)
        return sections

    # ---- Machinery ----------------------------------------------------------

    def _chunk_pages(self, text: str) -> list[str]:
        r"""Pack pages into ``<=chunk_chars`` windows; never split a page.

        Pages arrive ``\f``-separated from :meth:`preprocess_pdf`. A single
        page larger than ``chunk_chars`` becomes its own over-budget chunk: the
        whole page is still seen by the model, nothing is silently truncated.
        """
        chunks: list[str] = []
        buf = ""
        for page in text.split("\f"):
            page = page.strip()
            if not page:
                continue
            if buf and len(buf) + len(page) > self.chunk_chars:
                chunks.append(buf)
                buf = page
            else:
                buf = f"{buf}\n\n{page}" if buf else page
        if buf:
            chunks.append(buf)
        return chunks

    async def _map(self, chunks: list[str], meta: dict[str, Any]) -> dict[str, list[str]]:
        """Map each chunk; collect per-section fragments in chunk order.

        Section names the model invents (not present in ``self.schema``) are
        dropped; empty/whitespace fragments are ignored. Bounded by
        ``map_concurrency``: ``1`` (default) maps sequentially and fails fast on
        the first chunk error; ``>1`` fans chunks out under an
        ``asyncio.Semaphore`` while keeping fragment order identical to the
        sequential path (collected by chunk index, then flattened).
        """
        if self.map_concurrency < 1:
            raise ValueError(
                f"{type(self).__name__}: map_concurrency must be >= 1, got {self.map_concurrency}"
            )
        prompt = self.MAP_PROMPT.format(
            section_spec=self._section_spec(), **self.prompt_context(meta)
        )
        fragments: dict[str, list[str]] = defaultdict(list)

        # N == 1: sequential loop — fail-fast, byte-for-byte the prior behavior.
        if self.map_concurrency == 1:
            for chunk in chunks:
                self._collect(fragments, await self._cached_map_call(prompt, chunk))
            return dict(fragments)

        # N > 1: bounded fan-out. On the first chunk error, chunks still queued
        # behind the semaphore skip their model call (abort flag); in-flight
        # siblings run to completion and cache their successes before we raise.
        sem = asyncio.Semaphore(self.map_concurrency)
        aborted = asyncio.Event()

        async def _map_one(chunk: str) -> dict[str, Any]:
            async with sem:
                if aborted.is_set():
                    raise _MapChunkSkipped
                try:
                    return await self._cached_map_call(prompt, chunk)
                except Exception:
                    aborted.set()
                    raise

        results = await asyncio.gather(
            *(_map_one(chunk) for chunk in chunks), return_exceptions=True
        )
        # Collect successes in chunk-index order so output is completion-order
        # independent, then surface the first real error by index (skips aside).
        for result in results:
            if not isinstance(result, BaseException):
                self._collect(fragments, result)
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, _MapChunkSkipped):
                raise result
        return dict(fragments)

    def _collect(self, fragments: dict[str, list[str]], partial: dict[str, Any]) -> None:
        """Merge one chunk's map result into ``fragments`` in place.

        Section names not in ``self.schema`` are dropped (the model invented
        them); empty or whitespace-only values are ignored. Shared by both the
        sequential and fan-out paths so filtering is defined exactly once.
        """
        for name, value in partial.items():
            if self.schema.section(name) is None:
                continue  # ignore invented section names
            if isinstance(value, str) and value.strip():
                fragments[name].append(value.strip())

    # ---- Chunk-level map cache (overridable; no-op until enabled) ------------

    def _map_cache_key(self, prompt: str, chunk: str) -> str:
        """Fingerprint one map call into a content-addressed key.

        Keyed on the chunk text, the rendered ``MAP_PROMPT``, and the schema
        version — so editing the map prompt or bumping the schema invalidates
        the entry, while editing the *reduce* prompt does not (none of the map
        inputs moved). The model identity is intentionally excluded, matching
        :meth:`LLMExtractor.cache_key`: switching models does not invalidate the
        cache, so clear ``map_cache_dir`` by hand after a model swap.

        Args:
            prompt: The rendered map prompt sent with every chunk this run.
            chunk: The chunk text for this map call.

        Returns:
            A hex SHA-256 digest used as the cache entry's filename stem.
        """
        blob = f"{chunk}\x00{prompt}\x00{self.schema.version}".encode()
        return hashlib.sha256(blob).hexdigest()

    async def map_cache_get(self, key: str) -> dict[str, Any] | None:
        """Read a cached map fragment, or ``None`` on a miss.

        The default backend reads ``<key>.json`` from ``map_cache_dir``. A
        corrupt or unreadable entry is treated as a miss (re-extract) rather
        than a poisoned hit. Override to swap in a network or SQLite backend
        without touching :meth:`_map`.

        Args:
            key: The cache key from :meth:`_map_cache_key`.

        Returns:
            The cached parsed result, or ``None`` if the cache is disabled, the
            entry is absent, or the entry is unreadable.
        """
        if self.map_cache_dir is None:
            return None
        path = self.map_cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            return cast(dict[str, Any], json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError):
            return None  # corrupt entry -> treat as a miss, re-extract

    async def map_cache_put(self, key: str, result: dict[str, Any]) -> None:
        """Persist one successful map fragment for a future run.

        The default backend writes ``<key>.json`` under ``map_cache_dir`` via a
        temp file + atomic ``replace``, so a crash mid-write can't leave a
        half-written entry that later reads as a poisoned hit. Override alongside
        :meth:`map_cache_get` for a custom backend.

        Args:
            key: The cache key from :meth:`_map_cache_key`.
            result: The parsed map result to cache (never token usage).
        """
        if self.map_cache_dir is None:
            return
        self.map_cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.map_cache_dir / f"{key}.json.tmp"
        tmp.write_text(json.dumps(result))
        tmp.replace(self.map_cache_dir / f"{key}.json")

    async def _cached_map_call(self, prompt: str, chunk: str) -> dict[str, Any]:
        """Consult the map cache, falling back to :meth:`call_model` on a miss.

        On a hit the saved result is returned without a model call, so a hit
        adds zero tokens to ``_run_usage``. On a miss the model is called and the
        successful result is written back. Only the parsed ``dict`` is cached —
        never the :class:`TokenUsage` — so usage accounting reflects only the
        calls actually made.

        Args:
            prompt: The rendered map prompt for this run.
            chunk: The chunk text for this map call.

        Returns:
            The parsed map result for this chunk, cached or freshly extracted.
        """
        key = self._map_cache_key(prompt, chunk)
        hit = await self.map_cache_get(key)
        if hit is not None:
            return hit  # no call_model -> zero token spend
        result = await self.call_model(prompt, chunk)
        await self.map_cache_put(key, result)
        return result

    async def _reduce_section(self, name: str, frags: list[str], meta: dict[str, Any]) -> str:
        """Condense one section's fragments to fit its ``max_chars``.

        A single fragment that already fits is returned as-is (no model call).
        Otherwise the fragments are merged via ``REDUCE_PROMPT``. The final
        ``max_chars`` bound is guaranteed by :meth:`_enforce_max_chars`.
        """
        spec = self.schema.section(name)
        cap = spec.max_chars if spec and spec.max_chars else None
        joined = "\n\n---\n\n".join(frags)[: self.reduce_input_chars]
        if len(frags) == 1 and (cap is None or len(joined) <= cap):
            return joined
        prompt = self.REDUCE_PROMPT.format(
            section=name,
            max_chars=cap if cap is not None else "",
            **self.prompt_context(meta),
        )
        response = await self.call_model(prompt, joined)
        return str(response.get("content", "")).strip()

    def _enforce_max_chars(self, sections: dict[str, str]) -> dict[str, str]:
        """Hard-bound every section to its schema ``max_chars`` (final guard)."""
        bounded: dict[str, str] = {}
        for name, body in sections.items():
            spec = self.schema.section(name)
            if spec is not None and spec.max_chars is not None:
                bounded[name] = body[: spec.max_chars]
            else:
                bounded[name] = body
        return bounded

    def _section_spec(self) -> str:
        """Render the schema's named sections into prompt text for the map.

        Glob sections (no fixed name) and ``MAP_EXCLUDE`` sections are omitted.
        """
        lines: list[str] = []
        for spec in self.schema.sections:
            if spec.is_glob or spec.name in self.MAP_EXCLUDE:
                continue
            limit = f"<={spec.max_chars} chars" if spec.max_chars else "no limit"
            lines.append(f"- {spec.name} ({limit})")
        return "\n".join(lines)

    # ---- Provenance ---------------------------------------------------------

    def _prompt_hash(self) -> str:
        """Hash both prompts so ``cache_key`` reflects map + reduce changes."""
        combined = f"{self.MAP_PROMPT}\x00{self.REDUCE_PROMPT}"
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()
