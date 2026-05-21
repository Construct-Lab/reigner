"""list_documents, list_versions, get_section — schema-derived signatures."""

from __future__ import annotations

import inspect

import pytest

from reigner.artifacts.schema import ArtifactSchema, SectionSpec
from reigner.tools.artifacts import ArtifactStore
from reigner.tools.artifacts.list import (
    build_get_section,
    build_list_documents,
    build_list_versions,
)

# ---- list_documents ------------------------------------------------------


@pytest.mark.asyncio
async def test_list_documents_enumerates_all(store: ArtifactStore) -> None:
    ld = build_list_documents(store)
    res = await ld()
    assert res["count"] == 3
    ids = {(d["entity_id"], d["version"]) for d in res["entities"]}
    assert ids == {("AAPL", "2024"), ("AAPL", "2023"), ("MSFT", "2024")}


@pytest.mark.asyncio
async def test_list_documents_filters_by_first_key(store: ArtifactStore) -> None:
    ld = build_list_documents(store)
    res = await ld(entity_id="AAPL")
    assert res["count"] == 2
    assert all(d["entity_id"] == "AAPL" for d in res["entities"])
    assert res["filters"] == {"entity_id": "AAPL"}


@pytest.mark.asyncio
async def test_list_documents_filters_by_second_key(store: ArtifactStore) -> None:
    ld = build_list_documents(store)
    res = await ld(version="2024")
    versions = {d["version"] for d in res["entities"]}
    assert versions == {"2024"}


def test_list_documents_signature_matches_schema_keys(store: ArtifactStore) -> None:
    ld = build_list_documents(store)
    sig = inspect.signature(ld)
    assert set(sig.parameters) == {"entity_id", "version"}
    schema = ld.__reigner_spec__.json_schema()  # type: ignore[attr-defined]
    assert set(schema["properties"]) == {"entity_id", "version"}


# ---- list_versions -------------------------------------------------------


@pytest.mark.asyncio
async def test_list_versions_returns_trailing_dir_names(store: ArtifactStore) -> None:
    lv = build_list_versions(store)
    res = await lv(entity_id="AAPL")
    assert res == ["2023", "2024"]


@pytest.mark.asyncio
async def test_list_versions_for_unknown_prefix_returns_empty(store: ArtifactStore) -> None:
    lv = build_list_versions(store)
    res = await lv(entity_id="GOOGL")
    assert res == []


@pytest.mark.asyncio
async def test_list_versions_rejects_path_separator(store: ArtifactStore) -> None:
    lv = build_list_versions(store)
    with pytest.raises(ValueError, match="cannot contain path separators"):
        await lv(entity_id="../etc")


def test_list_versions_signature_excludes_trailing_key(store: ArtifactStore) -> None:
    lv = build_list_versions(store)
    sig = inspect.signature(lv)
    assert list(sig.parameters) == ["entity_id"]
    schema = lv.__reigner_spec__.json_schema()  # type: ignore[attr-defined]
    assert set(schema["properties"]) == {"entity_id"}


def test_list_versions_with_single_key_schema_takes_no_args(tmp_path) -> None:
    """When entity_path is a single placeholder, list_versions takes 0 args."""
    schema = ArtifactSchema(
        entity_path="{doc_id}",
        sections=[SectionSpec(name="summary")],
    )
    root = tmp_path / "lib"
    (root / "doc1").mkdir(parents=True)
    (root / "doc1" / "summary").write_text("hi")
    (root / "doc2").mkdir(parents=True)
    store = ArtifactStore(root, schema)
    lv = build_list_versions(store)
    sig = inspect.signature(lv)
    assert list(sig.parameters) == []


# ---- get_section ---------------------------------------------------------


@pytest.mark.asyncio
async def test_get_section_reads_named_file(store: ArtifactStore) -> None:
    gs = build_get_section(store)
    res = await gs(section="document_summary", entity_id="AAPL", version="2024")
    assert "Apple FY2024" in res["content"]
    assert res["section"] == "document_summary"
    assert res["path"] == "AAPL/2024/document_summary"
    assert res["size"] == len(res["content"])


@pytest.mark.asyncio
async def test_get_section_supports_nested(store: ArtifactStore) -> None:
    gs = build_get_section(store)
    res = await gs(section="sections/business", entity_id="AAPL", version="2024")
    assert "iPhone" in res["content"]


@pytest.mark.asyncio
async def test_get_section_missing_raises(store: ArtifactStore) -> None:
    gs = build_get_section(store)
    with pytest.raises(FileNotFoundError, match="not found under entity"):
        await gs(section="no_such", entity_id="AAPL", version="2024")


@pytest.mark.asyncio
async def test_get_section_missing_entity_raises(store: ArtifactStore) -> None:
    gs = build_get_section(store)
    with pytest.raises(FileNotFoundError):
        await gs(section="document_summary", entity_id="NOPE", version="2024")


@pytest.mark.asyncio
async def test_get_section_rejects_traversal_in_name(store: ArtifactStore) -> None:
    gs = build_get_section(store)
    with pytest.raises(ValueError, match="traversal"):
        await gs(section="../../etc", entity_id="AAPL", version="2024")


def test_get_section_signature_has_all_keys(store: ArtifactStore) -> None:
    gs = build_get_section(store)
    sig = inspect.signature(gs)
    assert list(sig.parameters) == ["section", "entity_id", "version"]
    schema = gs.__reigner_spec__.json_schema()  # type: ignore[attr-defined]
    assert set(schema["properties"]) == {"section", "entity_id", "version"}
