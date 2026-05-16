"""Tests for IngestionPipeline (T-16).

The tests use a :class:`_StubTransform` instead of going through
``LLMExtractor`` — the pipeline cares about the :class:`Transform` protocol
(``.run`` + ``.cache_key``), not which concrete type satisfies it.
``ArtifactSchema`` + ``ArtifactWriter`` are exercised real, so idempotency
and the on-disk shape are covered end-to-end.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from reigner.artifacts import ArtifactSchema, ArtifactWriter, JsonArtifactSpec, SectionSpec
from reigner.harness.events import ErrorEvent, StatusEvent
from reigner.ingestion import (
    Bm25IndexWriter,
    ExtractionResult,
    IngestionPipeline,
    LoadedDocument,
    ValidationError,
)
from reigner.ingestion.loaders.json_doc import JsonLoader
from reigner.ingestion.loaders.markdown import MdLoader

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubTransform:
    """In-process transform — no LLM, no extractor base class needed.

    ``cache_key`` and the ``ExtractionResult.meta`` written to disk must agree
    on ``(source_hash, schema_version, prompt_hash)`` for idempotency to work,
    so we centralise both here.
    """

    def __init__(
        self,
        *,
        side_effect: Exception | None = None,
        prompt_version: str = "v1",
    ) -> None:
        self._side_effect = side_effect
        self._prompt_version = prompt_version
        self.calls: list[tuple[bytes, dict[str, Any]]] = []

    async def run(self, raw: bytes, meta: dict[str, Any]) -> ExtractionResult:
        self.calls.append((raw, dict(meta)))
        if self._side_effect is not None:
            raise self._side_effect
        return self._build_result(raw, meta)

    def cache_key(self, raw: bytes) -> str:
        return f"{_sha256(raw)}:1:{self._prompt_version}"

    def _build_result(self, raw: bytes, meta: dict[str, Any]) -> ExtractionResult:
        ids = meta.get("identifiers", {})
        return ExtractionResult(
            sections={"document_summary": f"doc for {ids}"},
            json_artifacts={
                "metadata.json": {
                    "ticker": str(ids.get("ticker", "X")),
                    "fiscal_year": str(ids.get("fiscal_year", "0")),
                },
            },
            meta={
                "source_hash": _sha256(raw),
                "prompt_hash": self._prompt_version,
                "schema_version": "1",
                "model": "stub:stub-model",
                "tokens_in": 10,
                "tokens_out": 20,
                "cost_usd": 0.01,
            },
        )


def _sha256(raw: bytes) -> str:
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def _ok_result(meta: dict[str, Any]) -> ExtractionResult:
    """Shape mirrored by `_StubTransform._build_result`; used directly by tests
    that bypass the transform (e.g. selective-failure subclasses)."""
    return _StubTransform()._build_result(b"_", meta)


def _schema() -> ArtifactSchema:
    return ArtifactSchema(
        entity_path="{ticker}/{fiscal_year}",
        sections=[SectionSpec(name="document_summary", required=True)],
        json_artifacts=[
            JsonArtifactSpec(
                name="metadata.json",
                fields={"ticker": str, "fiscal_year": str},
            )
        ],
    )


def _md_loader_with_identifiers() -> MdLoader:
    def parse(p: Path) -> dict[str, Any]:
        ticker, _, year = p.stem.partition("_")
        return {"identifiers": {"ticker": ticker, "fiscal_year": year}}

    return MdLoader(meta_extractor=parse)


def _write_sources(tmp_path: Path, names: list[str]) -> Path:
    src = tmp_path / "raw"
    src.mkdir()
    for n in names:
        (src / n).write_bytes(f"# {n}\n".encode())
    return src


# ---------------------------------------------------------------------------
# Construction validation
# ---------------------------------------------------------------------------


def test_rejects_empty_loaders() -> None:
    with pytest.raises(ValueError, match="loaders cannot be empty"):
        IngestionPipeline(
            loaders=[],
            transforms=[_StubTransform()],
            writers=[ArtifactWriter(root="/tmp", schema=_schema())],
        )


def test_rejects_zero_or_multiple_transforms() -> None:
    schema = _schema()
    with pytest.raises(ValueError, match="exactly one transform"):
        IngestionPipeline(
            loaders=[MdLoader()],
            transforms=[],
            writers=[ArtifactWriter(root="/tmp", schema=schema)],
        )
    with pytest.raises(ValueError, match="exactly one transform"):
        IngestionPipeline(
            loaders=[MdLoader()],
            transforms=[_StubTransform(), _StubTransform()],
            writers=[ArtifactWriter(root="/tmp", schema=schema)],
        )


def test_rejects_empty_writers() -> None:
    with pytest.raises(ValueError, match="writers cannot be empty"):
        IngestionPipeline(
            loaders=[MdLoader()],
            transforms=[_StubTransform()],
            writers=[],
        )


def test_rejects_unknown_on_error() -> None:
    with pytest.raises(ValueError, match="on_error must be one of"):
        IngestionPipeline(
            loaders=[MdLoader()],
            transforms=[_StubTransform()],
            writers=[ArtifactWriter(root="/tmp", schema=_schema())],
            on_error="boom",  # type: ignore[arg-type]
        )


def test_rejects_dead_letter_without_path() -> None:
    with pytest.raises(ValueError, match="dead_letter_path is required"):
        IngestionPipeline(
            loaders=[MdLoader()],
            transforms=[_StubTransform()],
            writers=[ArtifactWriter(root="/tmp", schema=_schema())],
            on_error="dead_letter",
        )


def test_rejects_concurrency_below_one() -> None:
    with pytest.raises(ValueError, match="concurrency must be >= 1"):
        IngestionPipeline(
            loaders=[MdLoader()],
            transforms=[_StubTransform()],
            writers=[ArtifactWriter(root="/tmp", schema=_schema())],
            concurrency=0,
        )


def test_rejects_loaders_with_conflicting_extensions() -> None:
    class _OtherMd(MdLoader):
        pass

    with pytest.raises(ValueError, match="two loaders claim extension"):
        IngestionPipeline(
            loaders=[MdLoader(), _OtherMd()],
            transforms=[_StubTransform()],
            writers=[ArtifactWriter(root="/tmp", schema=_schema())],
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_happy_path_writes_entities_and_returns_report(tmp_path: Path) -> None:
    raw = _write_sources(tmp_path, ["AAPL_2024.md", "MSFT_2023.md"])
    schema = _schema()
    artifacts = tmp_path / "artifacts"
    pipeline = IngestionPipeline(
        loaders=[_md_loader_with_identifiers()],
        transforms=[_StubTransform()],
        writers=[ArtifactWriter(root=artifacts, schema=schema)],
        concurrency=2,
    )

    report = await pipeline.run(raw)

    assert report.succeeded == 2
    assert report.failed == 0
    assert report.skipped == 0
    assert report.total_tokens == (10 + 20) * 2
    assert report.total_cost_usd == pytest.approx(0.02)
    assert report.wall_clock_seconds >= 0.0

    # On-disk artifacts exist and contain the expected pieces.
    assert (artifacts / "AAPL" / "2024" / "document_summary").exists()
    assert (artifacts / "MSFT" / "2023" / "metadata.json").exists()
    manifest = json.loads((artifacts / "AAPL" / "2024" / "extraction_meta.json").read_text())
    assert manifest["identifiers"] == {"ticker": "AAPL", "fiscal_year": "2024"}
    assert manifest["extractor"]["model"] == "stub:stub-model"


async def test_run_stream_emits_status_events(tmp_path: Path) -> None:
    raw = _write_sources(tmp_path, ["AAPL_2024.md"])
    pipeline = IngestionPipeline(
        loaders=[_md_loader_with_identifiers()],
        transforms=[_StubTransform()],
        writers=[ArtifactWriter(root=tmp_path / "a", schema=_schema())],
    )
    events = [evt async for evt in pipeline.run_stream(raw)]
    assert all(isinstance(e, StatusEvent | ErrorEvent) for e in events)
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs)  # monotonic
    messages = [e.message for e in events if isinstance(e, StatusEvent)]
    assert any("discovered 1 sources" in m for m in messages)
    assert any("completed AAPL_2024.md" in m for m in messages)
    assert any("ingestion complete: 1 ok" in m for m in messages)


async def test_routes_files_by_extension(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "AAPL_2024.md").write_bytes(b"# md\n")
    (raw / "AAPL_2023.json").write_bytes(b'{"k": 1}')
    (raw / "notes.txt").write_bytes(b"unhandled")  # no loader; ignored

    def md_meta(p: Path) -> dict[str, Any]:
        t, _, y = p.stem.partition("_")
        return {"identifiers": {"ticker": t, "fiscal_year": y}}

    pipeline = IngestionPipeline(
        loaders=[MdLoader(meta_extractor=md_meta), JsonLoader(meta_extractor=md_meta)],
        transforms=[_StubTransform()],
        writers=[ArtifactWriter(root=tmp_path / "a", schema=_schema())],
    )
    report = await pipeline.run(raw)
    assert report.succeeded == 2
    assert report.failed == 0  # .txt is silently skipped (no loader)


async def test_writer_fan_out_to_bm25(tmp_path: Path) -> None:
    raw = _write_sources(tmp_path, ["AAPL_2024.md"])
    pipeline = IngestionPipeline(
        loaders=[_md_loader_with_identifiers()],
        transforms=[_StubTransform()],
        writers=[
            ArtifactWriter(root=tmp_path / "a", schema=_schema()),
            Bm25IndexWriter(path=tmp_path / "idx.json"),
        ],
    )
    await pipeline.run(raw)
    idx = json.loads((tmp_path / "idx.json").read_text())
    assert idx[0]["identifiers"] == {"ticker": "AAPL", "fiscal_year": "2024"}


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


async def test_skips_already_ingested_documents(tmp_path: Path) -> None:
    raw = _write_sources(tmp_path, ["AAPL_2024.md"])
    schema = _schema()
    transform = _StubTransform()
    pipeline = IngestionPipeline(
        loaders=[_md_loader_with_identifiers()],
        transforms=[transform],
        writers=[ArtifactWriter(root=tmp_path / "a", schema=schema)],
    )
    # First run extracts and writes.
    first = await pipeline.run(raw)
    assert first.succeeded == 1
    assert len(transform.calls) == 1

    # Second run with identical inputs should skip without re-calling the transform.
    second = await pipeline.run(raw)
    assert second.succeeded == 0
    assert second.skipped == 1
    assert len(transform.calls) == 1


async def test_prompt_change_invalidates_idempotency(tmp_path: Path) -> None:
    raw = _write_sources(tmp_path, ["AAPL_2024.md"])
    schema = _schema()
    artifacts = tmp_path / "a"
    first_transform = _StubTransform(prompt_version="v1")
    await IngestionPipeline(
        loaders=[_md_loader_with_identifiers()],
        transforms=[first_transform],
        writers=[ArtifactWriter(root=artifacts, schema=schema)],
    ).run(raw)

    # New prompt version → cache_key differs → re-extract.
    second_transform = _StubTransform(prompt_version="v2")
    report = await IngestionPipeline(
        loaders=[_md_loader_with_identifiers()],
        transforms=[second_transform],
        writers=[ArtifactWriter(root=artifacts, schema=schema)],
    ).run(raw)
    assert report.succeeded == 1
    assert report.skipped == 0
    assert len(second_transform.calls) == 1


async def test_no_idempotency_without_artifact_writer(tmp_path: Path) -> None:
    """Bm25IndexWriter alone can't anchor idempotency — extract every time."""
    raw = _write_sources(tmp_path, ["AAPL_2024.md"])
    transform = _StubTransform()
    pipeline = IngestionPipeline(
        loaders=[_md_loader_with_identifiers()],
        transforms=[transform],
        writers=[Bm25IndexWriter(path=tmp_path / "idx.json")],
    )
    await pipeline.run(raw)
    await pipeline.run(raw)
    assert len(transform.calls) == 2


# ---------------------------------------------------------------------------
# Error policies
# ---------------------------------------------------------------------------


async def test_on_error_raise_propagates(tmp_path: Path) -> None:
    raw = _write_sources(tmp_path, ["AAPL_2024.md"])
    pipeline = IngestionPipeline(
        loaders=[_md_loader_with_identifiers()],
        transforms=[_StubTransform(side_effect=RuntimeError("boom"))],
        writers=[ArtifactWriter(root=tmp_path / "a", schema=_schema())],
        on_error="raise",
    )
    with pytest.raises(RuntimeError, match="boom"):
        await pipeline.run(raw)


async def test_on_error_skip_records_failure_without_dead_letter(tmp_path: Path) -> None:
    raw = _write_sources(tmp_path, ["AAPL_2024.md", "MSFT_2023.md"])
    transform = _StubTransform(
        side_effect=RuntimeError("transient model error"),
    )
    pipeline = IngestionPipeline(
        loaders=[_md_loader_with_identifiers()],
        transforms=[transform],
        writers=[ArtifactWriter(root=tmp_path / "a", schema=_schema())],
        on_error="skip",
    )
    report = await pipeline.run(raw)
    assert report.failed == 2
    assert report.succeeded == 0
    assert report.dead_lettered == []
    assert all(f.error_type == "RuntimeError" for f in report.failures)


async def test_on_error_dead_letter_writes_raw_and_error(tmp_path: Path) -> None:
    raw = _write_sources(tmp_path, ["AAPL_2024.md"])
    dl_root = tmp_path / "_dead_letter"
    pipeline = IngestionPipeline(
        loaders=[_md_loader_with_identifiers()],
        transforms=[_StubTransform(side_effect=RuntimeError("nope"))],
        writers=[ArtifactWriter(root=tmp_path / "a", schema=_schema())],
        on_error="dead_letter",
        dead_letter_path=dl_root,
    )
    report = await pipeline.run(raw)
    assert report.failed == 1
    assert len(report.dead_lettered) == 1
    dl_dir = report.dead_lettered[0]
    assert (dl_dir / "raw.md").read_bytes() == b"# AAPL_2024.md\n"
    err = json.loads((dl_dir / "error.json").read_text())
    assert err["error_type"] == "RuntimeError"
    assert err["message"] == "nope"
    assert "traceback" in err
    # No ValidationError → no payload.json
    assert not (dl_dir / "payload.json").exists()


async def test_dead_letter_preserves_validation_payload(tmp_path: Path) -> None:
    raw = _write_sources(tmp_path, ["AAPL_2024.md"])
    bad_payload = {"sections": {"document_summary": None}, "json_artifacts": {}}
    pipeline = IngestionPipeline(
        loaders=[_md_loader_with_identifiers()],
        transforms=[
            _StubTransform(
                side_effect=ValidationError("required section missing", payload=bad_payload)
            )
        ],
        writers=[ArtifactWriter(root=tmp_path / "a", schema=_schema())],
        on_error="dead_letter",
        dead_letter_path=tmp_path / "_dead_letter",
    )
    report = await pipeline.run(raw)
    dl_dir = report.dead_lettered[0]
    assert (dl_dir / "payload.json").exists()
    assert json.loads((dl_dir / "payload.json").read_text()) == bad_payload


async def test_partial_failure_does_not_block_other_documents(tmp_path: Path) -> None:
    raw = _write_sources(tmp_path, ["AAPL_2024.md", "BAD_FILE.md", "MSFT_2023.md"])

    async def run_fn(raw_bytes: bytes, meta: dict[str, Any]) -> ExtractionResult:
        if b"BAD_FILE" in raw_bytes:
            raise RuntimeError("targeted failure")
        return _ok_result(meta)

    class _Selective(_StubTransform):
        async def run(self, raw_bytes: bytes, meta: dict[str, Any]) -> ExtractionResult:
            return await run_fn(raw_bytes, meta)

    pipeline = IngestionPipeline(
        loaders=[_md_loader_with_identifiers()],
        transforms=[_Selective()],
        writers=[ArtifactWriter(root=tmp_path / "a", schema=_schema())],
        on_error="skip",
    )
    report = await pipeline.run(raw)
    assert report.succeeded == 2
    assert report.failed == 1


# ---------------------------------------------------------------------------
# Discovery edge cases
# ---------------------------------------------------------------------------


async def test_empty_directory_returns_zero_source_report(tmp_path: Path) -> None:
    src = tmp_path / "empty"
    src.mkdir()
    pipeline = IngestionPipeline(
        loaders=[MdLoader()],
        transforms=[_StubTransform()],
        writers=[ArtifactWriter(root=tmp_path / "a", schema=_schema())],
    )
    report = await pipeline.run(src)
    assert report.succeeded == report.failed == report.skipped == 0


async def test_missing_source_raises_fnf(tmp_path: Path) -> None:
    pipeline = IngestionPipeline(
        loaders=[MdLoader()],
        transforms=[_StubTransform()],
        writers=[ArtifactWriter(root=tmp_path / "a", schema=_schema())],
    )
    with pytest.raises(FileNotFoundError):
        await pipeline.run(tmp_path / "does-not-exist")


async def test_accepts_single_file_as_source(tmp_path: Path) -> None:
    raw = _write_sources(tmp_path, ["AAPL_2024.md"])
    pipeline = IngestionPipeline(
        loaders=[_md_loader_with_identifiers()],
        transforms=[_StubTransform()],
        writers=[ArtifactWriter(root=tmp_path / "a", schema=_schema())],
    )
    report = await pipeline.run(raw / "AAPL_2024.md")
    assert report.succeeded == 1


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------


async def test_custom_identifiers_fn_overrides_default(tmp_path: Path) -> None:
    raw = _write_sources(tmp_path, ["whatever.md"])

    def ids_from_meta(loaded: LoadedDocument) -> dict[str, Any]:
        return {"ticker": "FIXED", "fiscal_year": "2099"}

    pipeline = IngestionPipeline(
        loaders=[MdLoader()],
        transforms=[_StubTransform()],
        writers=[ArtifactWriter(root=tmp_path / "a", schema=_schema())],
        identifiers_fn=ids_from_meta,
    )
    report = await pipeline.run(raw)
    assert report.succeeded == 1
    assert (tmp_path / "a" / "FIXED" / "2099" / "document_summary").exists()


async def test_missing_identifiers_surfaces_writer_validation_error(
    tmp_path: Path,
) -> None:
    raw = _write_sources(tmp_path, ["AAPL_2024.md"])
    # MdLoader without a meta_extractor: loaded.meta has no "identifiers" key,
    # so the default identifiers_fn returns {}, and ArtifactWriter rejects it.
    pipeline = IngestionPipeline(
        loaders=[MdLoader()],
        transforms=[_StubTransform()],
        writers=[ArtifactWriter(root=tmp_path / "a", schema=_schema())],
        on_error="skip",
    )
    report = await pipeline.run(raw)
    assert report.failed == 1
    # SchemaValidationError raised inside ArtifactWriter.write_entity
    assert "missing identifier" in report.failures[0].message.lower()


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


async def test_respects_concurrency_limit(tmp_path: Path) -> None:
    raw = _write_sources(tmp_path, [f"AAPL_{2000 + i}.md" for i in range(6)])

    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    class _Tracking(_StubTransform):
        async def run(self, raw_bytes: bytes, meta: dict[str, Any]) -> ExtractionResult:
            nonlocal in_flight, peak
            async with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            try:
                await asyncio.sleep(0.02)
                return _ok_result(meta)
            finally:
                async with lock:
                    in_flight -= 1

    pipeline = IngestionPipeline(
        loaders=[_md_loader_with_identifiers()],
        transforms=[_Tracking()],
        writers=[ArtifactWriter(root=tmp_path / "a", schema=_schema())],
        concurrency=2,
    )
    await pipeline.run(raw)
    assert peak <= 2
