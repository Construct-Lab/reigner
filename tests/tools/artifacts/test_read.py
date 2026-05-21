"""read_artifact_file — bounded, paginated text reads."""

from __future__ import annotations

import pytest

from reigner.tools.artifacts import ArtifactStore
from reigner.tools.artifacts.read import build_read_artifact_file


@pytest.mark.asyncio
async def test_reads_full_small_file(store: ArtifactStore) -> None:
    read = build_read_artifact_file(store)
    res = await read(path="AAPL/2024/document_summary")
    assert "Apple FY2024" in res["content"]
    assert res["offset"] == 0
    assert res["has_more"] is False
    assert res["total_size"] == len(res["content"])


@pytest.mark.asyncio
async def test_paginates_with_offset_and_limit(store: ArtifactStore) -> None:
    read = build_read_artifact_file(store)
    res = await read(path="AAPL/2024/document_summary", offset=0, limit=5)
    assert res["content"] == "Apple"
    assert res["has_more"] is True
    assert res["total_size"] > 5

    res2 = await read(path="AAPL/2024/document_summary", offset=5, limit=5)
    assert res2["content"].startswith(" ")  # next 5 chars include the space


@pytest.mark.asyncio
async def test_rejects_non_text_extension(store: ArtifactStore, tmp_path) -> None:
    # Drop a binary-suffix file under root and try to read it.
    (store.root / "AAPL" / "2024" / "blob.bin").write_text("binary-ish")
    read = build_read_artifact_file(store)
    with pytest.raises(ValueError, match="not a readable text artifact"):
        await read(path="AAPL/2024/blob.bin")


@pytest.mark.asyncio
async def test_missing_file_raises(store: ArtifactStore) -> None:
    read = build_read_artifact_file(store)
    with pytest.raises(FileNotFoundError):
        await read(path="AAPL/2024/no_such_file.md")


@pytest.mark.asyncio
async def test_rejects_traversal(store: ArtifactStore) -> None:
    read = build_read_artifact_file(store)
    with pytest.raises(ValueError, match="escapes artifact root"):
        await read(path="../../etc/passwd")


@pytest.mark.asyncio
async def test_rejects_bad_offset_limit(store: ArtifactStore) -> None:
    read = build_read_artifact_file(store)
    with pytest.raises(ValueError, match="offset"):
        await read(path="AAPL/2024/document_summary", offset=-1)
    with pytest.raises(ValueError, match="limit"):
        await read(path="AAPL/2024/document_summary", limit=0)


@pytest.mark.asyncio
async def test_schema_yields_correct_args(store: ArtifactStore) -> None:
    read = build_read_artifact_file(store)
    schema = read.__reigner_spec__.json_schema()  # type: ignore[attr-defined]
    props = schema["properties"]
    assert set(props) == {"path", "offset", "limit"}


@pytest.mark.asyncio
async def test_extraction_meta_is_readable(store: ArtifactStore) -> None:
    """Operator-only files outside the schema spec must remain readable."""
    read = build_read_artifact_file(store)
    res = await read(path="AAPL/2024/extraction_meta.json")
    assert "schema_version" in res["content"]
