"""ArtifactStore — trust-boundary tests for resolve / resolve_entity / tools()."""

from __future__ import annotations

from pathlib import Path

import pytest

from reigner.artifacts.schema import ArtifactSchema
from reigner.tools.artifacts import ArtifactStore
from reigner.tools.base import ToolSpec


def test_resolve_returns_path_under_root(store: ArtifactStore) -> None:
    p = store.resolve("AAPL/2024/document_summary")
    assert p.is_file()
    assert p.is_relative_to(store.root)


def test_resolve_rejects_absolute_path(store: ArtifactStore) -> None:
    with pytest.raises(ValueError, match="must be relative"):
        store.resolve("/etc/passwd")


def test_resolve_rejects_traversal(store: ArtifactStore) -> None:
    with pytest.raises(ValueError, match="escapes artifact root"):
        store.resolve("../../etc/passwd")


def test_resolve_rejects_empty(store: ArtifactStore) -> None:
    with pytest.raises(ValueError):
        store.resolve("")


def test_resolve_rejects_traversal_via_nested(store: ArtifactStore) -> None:
    with pytest.raises(ValueError, match="escapes artifact root"):
        store.resolve("AAPL/../../outside")


def test_resolve_allows_extraction_meta(store: ArtifactStore) -> None:
    # Operator/manifest files outside the schema spec must still be readable.
    p = store.resolve("AAPL/2024/extraction_meta.json")
    assert p.is_file()


def test_resolve_entity_requires_all_keys(store: ArtifactStore) -> None:
    with pytest.raises(ValueError, match="missing identifier"):
        store.resolve_entity(entity_id="AAPL")


def test_resolve_entity_rejects_extra_keys(store: ArtifactStore) -> None:
    with pytest.raises(ValueError, match="unexpected identifier"):
        store.resolve_entity(entity_id="AAPL", version="2024", extra="x")


def test_resolve_entity_rejects_path_separators(store: ArtifactStore) -> None:
    with pytest.raises(ValueError, match="cannot contain path separators"):
        store.resolve_entity(entity_id="AAPL", version="../etc")


def test_resolve_entity_returns_dir(store: ArtifactStore) -> None:
    p = store.resolve_entity(entity_id="AAPL", version="2024")
    assert p.is_dir()


def test_tools_returns_six_tools(store: ArtifactStore) -> None:
    tools = store.tools()
    names = [t.name for t in tools]
    assert names == [
        "read_artifact_file",
        "grep_artifact",
        "get_json_field",
        "list_documents",
        "list_versions",
        "get_section",
    ]
    for t in tools:
        assert t.readonly is True
        assert isinstance(t.json_schema(), dict)


def test_tools_satisfy_runnable_tool_protocol(store: ArtifactStore) -> None:
    from reigner.harness.loop import RunnableTool

    for t in store.tools():
        assert isinstance(t, RunnableTool)


def test_tools_wrap_a_real_tool_spec(store: ArtifactStore) -> None:
    for t in store.tools():
        # The underlying spec from the @tool decorator must be present
        assert isinstance(t.spec, ToolSpec)


def test_store_with_no_root_dir(tmp_path: Path, schema: ArtifactSchema) -> None:
    # Resolving a missing dir is fine; reading from it should surface errors.
    store = ArtifactStore(tmp_path / "missing", schema)
    assert store.root == (tmp_path / "missing").resolve()
