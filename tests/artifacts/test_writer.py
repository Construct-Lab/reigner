from __future__ import annotations

import json
from pathlib import Path

import pytest

from reigner.artifacts.manifest import ExtractionMeta
from reigner.artifacts.schema import ArtifactSchema, JsonArtifactSpec, SectionSpec
from reigner.artifacts.writer import (
    ArtifactWriter,
    SchemaValidationError,
)


def _basic_schema() -> ArtifactSchema:
    return ArtifactSchema(
        entity_path="{ticker}/{fiscal_year}",
        sections=[
            SectionSpec(name="document_summary", required=True, max_chars=100),
            SectionSpec(name="sections/business"),
        ],
        json_artifacts=[
            JsonArtifactSpec(
                name="metadata.json",
                fields={"ticker": str, "fiscal_year": int},
            ),
        ],
    )


def test_happy_path(tmp_path: Path) -> None:
    schema = _basic_schema()
    writer = ArtifactWriter(root=tmp_path, schema=schema)
    dest = writer.write_entity(
        ticker="AAPL",
        fiscal_year="2024",
        sections={
            "document_summary": "Apple makes phones.",
            "sections/business": "Hardware and services.",
        },
        json_artifacts={
            "metadata.json": {"ticker": "AAPL", "fiscal_year": 2024},
        },
        meta={"source_hash": "abc123", "model": "claude-opus-4-7"},
    )
    assert dest == tmp_path / "AAPL" / "2024"
    assert (dest / "document_summary").read_text() == "Apple makes phones."
    assert (dest / "sections" / "business").read_text() == "Hardware and services."
    assert json.loads((dest / "metadata.json").read_text()) == {
        "ticker": "AAPL",
        "fiscal_year": 2024,
    }
    manifest = ExtractionMeta.from_json((dest / "extraction_meta.json").read_text())
    assert manifest.schema_version == "1"
    assert manifest.identifiers == {"ticker": "AAPL", "fiscal_year": "2024"}
    assert manifest.extractor == {"source_hash": "abc123", "model": "claude-opus-4-7"}
    assert "metadata.json" in manifest.files
    assert "document_summary" in manifest.files


def test_missing_identifier_raises_no_io(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path, schema=_basic_schema())
    with pytest.raises(SchemaValidationError, match="missing identifier"):
        writer.write_entity(ticker="AAPL")
    assert list(tmp_path.iterdir()) == []


def test_extra_identifier_raises(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path, schema=_basic_schema())
    with pytest.raises(SchemaValidationError, match="unexpected identifier"):
        writer.write_entity(ticker="AAPL", fiscal_year="2024", extra="nope")


def test_identifier_with_path_separator_raises(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path, schema=_basic_schema())
    with pytest.raises(SchemaValidationError, match="path separators"):
        writer.write_entity(ticker="AA/PL", fiscal_year="2024")


def test_missing_required_section_raises(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path, schema=_basic_schema())
    with pytest.raises(SchemaValidationError, match="missing required section"):
        writer.write_entity(
            ticker="AAPL",
            fiscal_year="2024",
            json_artifacts={"metadata.json": {"ticker": "AAPL", "fiscal_year": 2024}},
        )
    assert not (tmp_path / "AAPL").exists()


def test_max_chars_violation_raises(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path, schema=_basic_schema())
    with pytest.raises(SchemaValidationError, match="exceeds max_chars"):
        writer.write_entity(
            ticker="AAPL",
            fiscal_year="2024",
            sections={"document_summary": "x" * 101},
            json_artifacts={"metadata.json": {"ticker": "AAPL", "fiscal_year": 2024}},
        )


def test_missing_required_json_field_raises(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path, schema=_basic_schema())
    with pytest.raises(SchemaValidationError, match="missing required fields"):
        writer.write_entity(
            ticker="AAPL",
            fiscal_year="2024",
            sections={"document_summary": "ok"},
            json_artifacts={"metadata.json": {"ticker": "AAPL"}},
        )


def test_wrong_json_field_type_raises(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path, schema=_basic_schema())
    with pytest.raises(SchemaValidationError, match="expected int"):
        writer.write_entity(
            ticker="AAPL",
            fiscal_year="2024",
            sections={"document_summary": "ok"},
            json_artifacts={
                "metadata.json": {"ticker": "AAPL", "fiscal_year": "2024"},
            },
        )


def test_overwrite_replaces_cleanly(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path, schema=_basic_schema())
    common: dict[str, object] = {
        "ticker": "AAPL",
        "fiscal_year": "2024",
        "json_artifacts": {"metadata.json": {"ticker": "AAPL", "fiscal_year": 2024}},
    }
    writer.write_entity(sections={"document_summary": "first"}, **common)  # type: ignore[arg-type]
    writer.write_entity(sections={"document_summary": "second"}, **common)  # type: ignore[arg-type]
    dest = tmp_path / "AAPL" / "2024"
    assert (dest / "document_summary").read_text() == "second"
    # No leftover trash or staging
    assert not (tmp_path / ".trash").exists() or list((tmp_path / ".trash").iterdir()) == []
    assert not (tmp_path / ".staging").exists() or list((tmp_path / ".staging").iterdir()) == []


def test_validation_failure_leaves_no_partial_state(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path, schema=_basic_schema())
    with pytest.raises(SchemaValidationError):
        writer.write_entity(
            ticker="AAPL",
            fiscal_year="2024",
            sections={"document_summary": "ok"},
            json_artifacts={"metadata.json": {"ticker": "AAPL"}},  # missing field
        )
    assert not (tmp_path / "AAPL").exists()
    # Validation runs before any staging directory is created.
    assert not (tmp_path / ".staging").exists()


def test_unknown_section_under_glob_is_allowed(tmp_path: Path) -> None:
    schema = ArtifactSchema(
        entity_path="{entity_id}/{version}",
        sections=[
            SectionSpec(name="document_summary", required=True),
            SectionSpec(name="sections/*"),
        ],
        json_artifacts=[],
    )
    writer = ArtifactWriter(root=tmp_path, schema=schema)
    dest = writer.write_entity(
        entity_id="x",
        version="v1",
        sections={
            "document_summary": "ok",
            "sections/anything": "fine",
        },
    )
    assert (dest / "sections" / "anything").read_text() == "fine"


def test_optional_json_artifact_can_be_omitted(tmp_path: Path) -> None:
    schema = ArtifactSchema(
        entity_path="{entity_id}/{version}",
        sections=[SectionSpec(name="document_summary", required=True)],
        json_artifacts=[JsonArtifactSpec(name="optional.json")],  # no fields => optional
    )
    writer = ArtifactWriter(root=tmp_path, schema=schema)
    dest = writer.write_entity(
        entity_id="x",
        version="v1",
        sections={"document_summary": "ok"},
    )
    assert not (dest / "optional.json").exists()


def test_json_artifact_payload_must_be_dict(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path, schema=_basic_schema())
    with pytest.raises(SchemaValidationError, match="must be a dict"):
        writer.write_entity(
            ticker="AAPL",
            fiscal_year="2024",
            sections={"document_summary": "ok"},
            json_artifacts={"metadata.json": "not-a-dict"},  # type: ignore[dict-item]
        )


def test_entity_dir_resolves_under_root(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path, schema=_basic_schema())
    assert writer.entity_dir(ticker="AAPL", fiscal_year="2024") == (tmp_path / "AAPL" / "2024")
