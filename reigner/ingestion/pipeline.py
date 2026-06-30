"""IngestionPipeline — Layer C of the ingestion stack.

Walks a source directory, dispatches each file to the loader that owns its
extension, runs the configured transform (the user's
:class:`reigner.ingestion.LLMExtractor` subclass), then fans the extraction
out to each writer. Built to deliver five guarantees:

* **Concurrency** — ``asyncio.Semaphore``-bounded fan-out across documents.
* **Progress** — yields :class:`reigner.harness.events.StatusEvent` and
  :class:`ErrorEvent` instances via :meth:`run_stream`.
* **Idempotency** — for each candidate source, compares the transform's
  :meth:`Transform.cache_key` against the existing
  ``extraction_meta.json``'s ``extractor`` block in the destination entity
  directory; if every :class:`ArtifactWriter` already has a matching
  manifest the source is skipped.
* **Error policy** — ``raise`` (propagate), ``skip`` (log + continue), or
  ``dead_letter`` (raw bytes + ``error.json`` + optional ``payload.json``
  preserved under ``dead_letter_path/<source-id>/``).
* **Final report** — :class:`IngestionReport` with counts, summed tokens,
  summed cost, and wall-clock seconds. Available as
  :attr:`IngestionPipeline.last_report` after the stream drains, or returned
  directly by the convenience :meth:`run`.

Per-source events are buffered into a per-worker list and yielded together
when the worker finishes (via :func:`asyncio.as_completed`). Documents run
concurrently; each document's events stay coherent. v0 limits ``transforms``
to length one; the list shape is forward-compatible with non-LLM transforms
landing later.
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any, Literal, cast

from reigner.artifacts import ArtifactWriter, ExtractionMeta
from reigner.harness.events import ErrorEvent, Event, StatusEvent
from reigner.ingestion.loaders import LoadedDocument, Loader
from reigner.ingestion.results import ExtractionResult, ValidationError
from reigner.ingestion.writers.base import (
    IngestionReport,
    PipelineWriter,
    SourceFailure,
    Transform,
)

OnError = Literal["raise", "dead_letter", "skip"]
Writer = ArtifactWriter | PipelineWriter
IdentifiersFn = Callable[[LoadedDocument], dict[str, Any]]
SourceIdFn = Callable[[Path], str]


def _default_identifiers_fn(loaded: LoadedDocument) -> dict[str, Any]:
    """Default: pull ``loaded.meta["identifiers"]`` if the loader supplied it.

    The expected shape is a flat ``{key: value}`` mapping whose keys exactly
    match the ``ArtifactSchema.entity_path`` placeholders. The loader's
    ``meta_extractor`` is the usual place to derive these from a filename
    (e.g. ``AAPL_2024.pdf`` → ``{"ticker": "AAPL", "fiscal_year": "2024"}``).
    """
    ids = loaded.meta.get("identifiers")
    if isinstance(ids, dict):
        return dict(ids)
    return {}


def _default_source_id_fn(src: Path) -> str:
    return src.stem or src.name or "unknown"


class IngestionPipeline:
    """Concurrent runner that compiles a source directory into artifacts.

    Routes each source to a loader, applies the configured transform, and fans
    the result out to the writers, with idempotency, bounded concurrency, a
    configurable error policy, and a final :class:`IngestionReport`.
    """

    def __init__(
        self,
        *,
        loaders: Sequence[Loader],
        transforms: Sequence[Transform],
        writers: Sequence[Writer],
        concurrency: int = 4,
        on_error: OnError = "raise",
        dead_letter_path: str | Path | None = None,
        identifiers_fn: IdentifiersFn | None = None,
        source_id_fn: SourceIdFn | None = None,
        session_id: str | None = None,
    ) -> None:
        if not loaders:
            raise ValueError("loaders cannot be empty")
        if len(transforms) != 1:
            raise ValueError(f"v0 supports exactly one transform, got {len(transforms)}")
        if not writers:
            raise ValueError("writers cannot be empty")
        if on_error not in ("raise", "dead_letter", "skip"):
            raise ValueError(
                f"on_error must be one of 'raise', 'dead_letter', 'skip'; got {on_error!r}"
            )
        if on_error == "dead_letter" and dead_letter_path is None:
            raise ValueError("dead_letter_path is required when on_error='dead_letter'")
        if concurrency < 1:
            raise ValueError(f"concurrency must be >= 1, got {concurrency}")

        self._loaders = list(loaders)
        self._transform: Transform = transforms[0]
        self._writers: list[Writer] = list(writers)
        self._concurrency = concurrency
        self._on_error: OnError = on_error
        self._dead_letter_path = Path(dead_letter_path) if dead_letter_path else None
        self._identifiers_fn = identifiers_fn or _default_identifiers_fn
        self._source_id_fn = source_id_fn or _default_source_id_fn
        self._session_id = session_id or f"ingest-{uuid.uuid4().hex[:8]}"

        self._ext_to_loader = self._build_extension_map(self._loaders)
        self.last_report: IngestionReport | None = None

    @staticmethod
    def _build_extension_map(loaders: Sequence[Loader]) -> dict[str, Loader]:
        out: dict[str, Loader] = {}
        for loader in loaders:
            extensions = cast(frozenset[str], getattr(loader, "extensions", frozenset()))
            for ext in extensions:
                if ext in out:
                    raise ValueError(
                        f"two loaders claim extension {ext!r}: "
                        f"{type(out[ext]).__name__} and {type(loader).__name__}"
                    )
                out[ext.lower()] = loader
        return out

    # ---- Public API --------------------------------------------------------

    async def run(self, source: str | Path) -> IngestionReport:
        """Run end-to-end, discard events, return the final report."""
        async for _ in self.run_stream(source):
            pass
        assert self.last_report is not None
        return self.last_report

    async def run_stream(self, source: str | Path) -> AsyncIterator[Event]:
        """Run end-to-end, yielding progress events as workers complete.

        After the iterator drains, :attr:`last_report` holds the
        :class:`IngestionReport`. If ``on_error='raise'`` and a worker
        raises, remaining workers are cancelled and the exception propagates
        once their cancellation settles.
        """
        report = IngestionReport()
        self.last_report = report
        start_ts = time.monotonic()
        seq = _SeqCounter()

        sources = await asyncio.to_thread(self._discover, Path(source))
        yield self._status(seq.next(), f"discovered {len(sources)} sources")

        if not sources:
            report.wall_clock_seconds = time.monotonic() - start_ts
            yield self._status(seq.next(), "ingestion complete: 0 sources")
            return

        sem = asyncio.Semaphore(self._concurrency)

        async def worker(src: Path) -> list[Event]:
            events: list[Event] = []
            async with sem:
                await self._process_source(src, seq, events, report)
            return events

        tasks = [asyncio.create_task(worker(s)) for s in sources]

        try:
            for coro in asyncio.as_completed(tasks):
                worker_events = await coro
                for evt in worker_events:
                    yield evt
        except BaseException:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        report.wall_clock_seconds = time.monotonic() - start_ts
        yield self._status(
            seq.next(),
            f"ingestion complete: {report.succeeded} ok, "
            f"{report.failed} failed, {report.skipped} skipped",
        )

    # ---- Per-source machinery ---------------------------------------------

    async def _process_source(
        self,
        src: Path,
        seq: _SeqCounter,
        events: list[Event],
        report: IngestionReport,
    ) -> None:
        loader = self._ext_to_loader.get(src.suffix.lower())
        if loader is None:
            await self._handle_failure(
                src,
                None,
                None,
                _NoLoader(f"no loader registered for {src.suffix!r}"),
                seq,
                events,
                report,
            )
            return

        try:
            loaded = await loader.load(src)
        except Exception as exc:
            await self._handle_failure(src, None, None, exc, seq, events, report)
            return

        try:
            raw_ids = self._identifiers_fn(loaded)
            identifiers = {k: str(v) for k, v in raw_ids.items()}
        except Exception as exc:
            await self._handle_failure(src, loaded, None, exc, seq, events, report)
            return

        if self._is_already_extracted(loaded, identifiers):
            report.skipped += 1
            events.append(self._status(seq.next(), f"skipped {src.name} (already ingested)"))
            return

        try:
            result = await self._transform.run(loaded.raw, loaded.meta)
        except Exception as exc:
            await self._handle_failure(src, loaded, None, exc, seq, events, report)
            return

        try:
            for writer in self._writers:
                await self._invoke_writer(writer, loaded, result, identifiers)
        except Exception as exc:
            await self._handle_failure(src, loaded, result, exc, seq, events, report)
            return

        report.succeeded += 1
        tokens_in = int(result.meta.get("tokens_in", 0) or 0)
        tokens_out = int(result.meta.get("tokens_out", 0) or 0)
        report.total_tokens += tokens_in + tokens_out
        report.total_cost_usd += float(result.meta.get("cost_usd", 0.0) or 0.0)
        events.append(self._status(seq.next(), f"completed {src.name}"))

    async def _invoke_writer(
        self,
        writer: Writer,
        loaded: LoadedDocument,
        result: ExtractionResult,
        identifiers: dict[str, str],
    ) -> None:
        if isinstance(writer, ArtifactWriter):
            await asyncio.to_thread(
                _write_entity_blocking,
                writer,
                identifiers,
                result,
            )
        else:
            await writer.write(loaded=loaded, result=result, identifiers=identifiers)

    def _is_already_extracted(self, loaded: LoadedDocument, identifiers: dict[str, str]) -> bool:
        artifact_writers = [w for w in self._writers if isinstance(w, ArtifactWriter)]
        if not artifact_writers:
            # No canonical store on disk; we can't prove anything.
            return False
        if not identifiers:
            # Can't resolve an entity_dir without identifiers.
            return False
        expected_key = self._transform.cache_key(loaded.raw)
        for writer in artifact_writers:
            try:
                entity_dir = writer.entity_dir(**identifiers)
            except Exception:
                # Identifier mismatch with schema; treat as not-yet-extracted
                # so the writer's own validation surfaces the real error.
                return False
            meta_path = entity_dir / writer.schema.extraction_meta
            if not meta_path.exists():
                return False
            try:
                manifest = ExtractionMeta.from_json(meta_path.read_text())
            except (OSError, json.JSONDecodeError, KeyError):
                return False
            existing_key = _manifest_cache_key(manifest)
            if existing_key != expected_key:
                return False
        return True

    async def _handle_failure(
        self,
        src: Path,
        loaded: LoadedDocument | None,
        result: ExtractionResult | None,
        exc: BaseException,
        seq: _SeqCounter,
        events: list[Event],
        report: IngestionReport,
    ) -> None:
        if self._on_error == "raise":
            raise exc

        error_type = type(exc).__name__
        message = str(exc) or error_type
        events.append(
            self._error(
                seq.next(),
                f"{src.name}: {error_type}: {message}",
                recoverable=True,
            )
        )

        failure = SourceFailure(source=str(src), error_type=error_type, message=message)
        report.failed += 1

        if self._on_error == "dead_letter":
            dl_path = await asyncio.to_thread(self._write_dead_letter, src, loaded, result, exc)
            failure.dead_letter_path = dl_path
            report.dead_lettered.append(dl_path)

        report.failures.append(failure)

    def _write_dead_letter(
        self,
        src: Path,
        loaded: LoadedDocument | None,
        result: ExtractionResult | None,
        exc: BaseException,
    ) -> Path:
        assert self._dead_letter_path is not None
        dl_dir = self._dead_letter_path / self._source_id_fn(src)
        dl_dir.mkdir(parents=True, exist_ok=True)

        if loaded is not None:
            ext = src.suffix or ".bin"
            (dl_dir / f"raw{ext}").write_bytes(loaded.raw)

        error_payload = {
            "source": str(src),
            "error_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
        }
        (dl_dir / "error.json").write_text(json.dumps(error_payload, indent=2))

        if isinstance(exc, ValidationError) and exc.payload is not None:
            (dl_dir / "payload.json").write_text(
                json.dumps(exc.payload, indent=2, default=str, sort_keys=True)
            )
        elif result is not None:
            (dl_dir / "payload.json").write_text(
                json.dumps(
                    {
                        "sections": dict(result.sections),
                        "json_artifacts": dict(result.json_artifacts),
                    },
                    indent=2,
                    default=str,
                    sort_keys=True,
                )
            )

        return dl_dir

    # ---- Discovery ---------------------------------------------------------

    def _discover(self, source: Path) -> list[Path]:
        if source.is_file():
            return [source]
        if not source.exists():
            raise FileNotFoundError(f"source not found: {source}")
        if not source.is_dir():
            raise NotADirectoryError(f"source is not a file or directory: {source}")
        out: list[Path] = []
        for child in sorted(source.rglob("*")):
            if child.is_file() and child.suffix.lower() in self._ext_to_loader:
                out.append(child)
        return out

    # ---- Event helpers -----------------------------------------------------

    def _status(self, seq_num: int, message: str) -> StatusEvent:
        return StatusEvent(seq=seq_num, session_id=self._session_id, turn=0, message=message)

    def _error(self, seq_num: int, msg: str, *, recoverable: bool) -> ErrorEvent:
        return ErrorEvent(
            seq=seq_num,
            session_id=self._session_id,
            turn=0,
            error=msg,
            recoverable=recoverable,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_entity_blocking(
    writer: ArtifactWriter,
    identifiers: dict[str, str],
    result: ExtractionResult,
) -> Path:
    return writer.write_entity(
        sections=result.sections,
        json_artifacts=result.json_artifacts,
        meta=result.meta,
        **identifiers,
    )


def _manifest_cache_key(manifest: ExtractionMeta) -> str:
    ext = manifest.extractor or {}
    return (
        f"{ext.get('source_hash', '')}:{ext.get('schema_version', '')}:{ext.get('prompt_hash', '')}"
    )


class _SeqCounter:
    """Monotonic event sequence within one pipeline run.

    Single-threaded asyncio: read-then-increment with no intervening await is
    atomic, so we don't need a lock.
    """

    def __init__(self) -> None:
        self._n = 0

    def next(self) -> int:
        n = self._n
        self._n += 1
        return n


class _NoLoader(RuntimeError):
    """Raised internally when ``_discover`` somehow surfaces an unhandled suffix."""
