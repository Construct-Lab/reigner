"""grep_artifact — literal-substring search."""

from __future__ import annotations

import pytest

from reigner.tools.artifacts import ArtifactStore
from reigner.tools.artifacts.grep import build_grep_artifact


@pytest.mark.asyncio
async def test_finds_substring_across_entities(store: ArtifactStore) -> None:
    grep = build_grep_artifact(store)
    res = await grep(query="summary")
    assert res["total_files_searched"] > 0
    assert all("summary" in m["line"].lower() for m in res["matches"])


@pytest.mark.asyncio
async def test_entity_scope_limits_search(store: ArtifactStore) -> None:
    grep = build_grep_artifact(store)
    res = await grep(query="summary", entity="AAPL/2024")
    rels = {m["path"] for m in res["matches"]}
    assert all(r.startswith("AAPL/2024") for r in rels)


@pytest.mark.asyncio
async def test_case_insensitive(store: ArtifactStore) -> None:
    grep = build_grep_artifact(store)
    res = await grep(query="APPLE", case_insensitive=True)
    assert len(res["matches"]) > 0


@pytest.mark.asyncio
async def test_match_cap_truncates(store: ArtifactStore, tmp_path) -> None:
    # Generate 20 matches in a single file, expect cap of 10.
    (store.root / "AAPL" / "2024" / "many.md").write_text(
        "\n".join(f"hit line {i}" for i in range(20))
    )
    grep = build_grep_artifact(store)
    res = await grep(query="hit")
    assert res["truncated"] is True
    assert len(res["matches"]) == 10


@pytest.mark.asyncio
async def test_file_path_limits_to_one_file(store: ArtifactStore) -> None:
    grep = build_grep_artifact(store)
    res = await grep(query="Apple", file_path="AAPL/2024/document_summary")
    rels = {m["path"] for m in res["matches"]}
    assert rels == {"AAPL/2024/document_summary"}


@pytest.mark.asyncio
async def test_extensions_filter(store: ArtifactStore) -> None:
    grep = build_grep_artifact(store)
    res = await grep(query="revenue", extensions=[".json"])
    assert all(m["path"].endswith(".json") for m in res["matches"])


@pytest.mark.asyncio
async def test_traversal_rejected(store: ArtifactStore) -> None:
    grep = build_grep_artifact(store)
    with pytest.raises(ValueError, match="escapes artifact root"):
        await grep(query="x", entity="../..")


@pytest.mark.asyncio
async def test_empty_query_rejected(store: ArtifactStore) -> None:
    grep = build_grep_artifact(store)
    with pytest.raises(ValueError):
        await grep(query="")
