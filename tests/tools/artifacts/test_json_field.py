"""get_json_field — bounded, self-describing JSON field extraction."""

from __future__ import annotations

import pytest

from reigner.tools.artifacts import ArtifactStore
from reigner.tools.artifacts.json_field import build_get_json_field


@pytest.mark.asyncio
async def test_extracts_requested_fields(store: ArtifactStore) -> None:
    gjf = build_get_json_field(store)
    res = await gjf(path="AAPL/2024/metadata.json", fields=["revenue", "research_and_development"])
    assert res["fields"]["revenue"] == 391000000000
    assert res["fields"]["research_and_development"] == 31370000000
    assert res["missing_keys"] == []


@pytest.mark.asyncio
async def test_reports_missing_keys_and_available_keys(store: ArtifactStore) -> None:
    gjf = build_get_json_field(store)
    res = await gjf(path="AAPL/2024/metadata.json", fields=["ebitda"])
    assert res["fields"] == {}
    assert res["missing_keys"] == ["ebitda"]
    assert "revenue" in res["available_keys"]
    # Sorted for deterministic enumeration by the model.
    assert res["available_keys"] == sorted(res["available_keys"])


@pytest.mark.asyncio
async def test_rejects_non_json_suffix(store: ArtifactStore) -> None:
    gjf = build_get_json_field(store)
    with pytest.raises(ValueError, match="not a .json artifact"):
        await gjf(path="AAPL/2024/document_summary", fields=["x"])


@pytest.mark.asyncio
async def test_missing_file_raises(store: ArtifactStore) -> None:
    gjf = build_get_json_field(store)
    with pytest.raises(FileNotFoundError):
        await gjf(path="AAPL/2024/no_such.json", fields=["x"])


@pytest.mark.asyncio
async def test_rejects_non_object_top_level(store: ArtifactStore) -> None:
    (store.root / "AAPL" / "2024" / "list.json").write_text("[1, 2, 3]")
    gjf = build_get_json_field(store)
    with pytest.raises(ValueError, match="top-level must be a JSON object"):
        await gjf(path="AAPL/2024/list.json", fields=["x"])


@pytest.mark.asyncio
async def test_traversal_rejected(store: ArtifactStore) -> None:
    gjf = build_get_json_field(store)
    with pytest.raises(ValueError, match="escapes artifact root"):
        await gjf(path="../etc/passwd.json", fields=["x"])
