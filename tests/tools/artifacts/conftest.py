"""Shared fixtures for artifact-tools tests.

Lays down a tiny document_qa-shaped artifact tree:
    library/artifacts/
        AAPL/2024/
            document_summary       (text section)
            sections/business      (nested section)
            metadata.json
            extraction_meta.json   (operator/manifest file, readable but not in schema)
        AAPL/2023/
            document_summary
            metadata.json
        MSFT/2024/
            document_summary
            metadata.json
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reigner.artifacts.schema import ArtifactSchema, JsonArtifactSpec, SectionSpec
from reigner.tools.artifacts import ArtifactStore


def _write_entity(
    root: Path,
    *,
    ticker: str,
    year: str,
    summary: str,
    business: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    ent = root / ticker / year
    ent.mkdir(parents=True, exist_ok=True)
    (ent / "document_summary").write_text(summary)
    if business is not None:
        (ent / "sections").mkdir(exist_ok=True)
        (ent / "sections" / "business").write_text(business)
    if metadata is not None:
        (ent / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True))
    (ent / "extraction_meta.json").write_text(
        json.dumps(
            {"schema_version": "1", "identifiers": {"entity_id": ticker, "version": year}},
            indent=2,
        )
    )


@pytest.fixture
def schema() -> ArtifactSchema:
    return ArtifactSchema(
        entity_path="{entity_id}/{version}",
        sections=[
            SectionSpec(name="document_summary"),
            SectionSpec(name="sections/*"),
        ],
        json_artifacts=[JsonArtifactSpec(name="metadata.json")],
    )


@pytest.fixture
def artifact_root(tmp_path: Path) -> Path:
    root = tmp_path / "library" / "artifacts"
    _write_entity(
        root,
        ticker="AAPL",
        year="2024",
        summary="Apple FY2024 summary — revenue beat",
        business="Apple sells iPhone hardware globally.",
        metadata={
            "revenue": 391000000000,
            "net_income": 96000000000,
            "research_and_development": 31370000000,
        },
    )
    _write_entity(
        root,
        ticker="AAPL",
        year="2023",
        summary="Apple FY2023 summary",
        metadata={"revenue": 383000000000, "net_income": 97000000000},
    )
    _write_entity(
        root,
        ticker="MSFT",
        year="2024",
        summary="Microsoft FY2024 summary",
        metadata={"revenue": 245000000000},
    )
    return root


@pytest.fixture
def store(artifact_root: Path, schema: ArtifactSchema) -> ArtifactStore:
    return ArtifactStore(artifact_root, schema)
