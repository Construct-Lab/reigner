from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from reigner.tools.base import ToolSpec
from reigner.tools.search import Bm25Index, SearchIndex


def _write_sidecar(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries))


def _funcs(index: Bm25Index) -> list:
    """Unwrap the adapters back to their underlying @tool callables for direct invocation."""
    return [t.spec.func for t in index.tools()]


def _entry(
    entry_id: str,
    text: str,
    *,
    identifiers: dict[str, str] | None = None,
    sections: dict[str, str] | None = None,
    source: str = "",
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "identifiers": identifiers or {},
        "text": text,
        "sections": sections if sections is not None else {"document_summary": text},
        "source": source,
    }


# ---------------------------------------------------------------------------
# Construction + tools() surface
# ---------------------------------------------------------------------------


def test_satisfies_search_index_protocol(tmp_path: Path) -> None:
    _write_sidecar(tmp_path / "idx.json", [])
    index = Bm25Index(path=tmp_path / "idx.json")
    assert isinstance(index, SearchIndex)
    assert Bm25Index.__reigner_backend__ == "search"


def test_tools_bearing_class_without_marker_is_not_a_search_index() -> None:
    """The __reigner_backend__ marker narrows SearchIndex past structural typing.

    A class that happens to expose tools() (e.g. a future FsTools or
    ArtifactStore) MUST NOT satisfy SearchIndex by accident — that's the
    whole reason the marker exists.
    """

    class FakeFsTools:
        def tools(self) -> list:  # same shape as Bm25Index.tools
            return []

    assert not isinstance(FakeFsTools(), SearchIndex)


def test_tools_returns_three_decorated_tools(tmp_path: Path) -> None:
    _write_sidecar(tmp_path / "idx.json", [])
    index = Bm25Index(path=tmp_path / "idx.json")
    tools = index.tools()
    names = [t.name for t in tools]
    assert names == ["bm25_search", "filtered_search", "section_search"]
    for t in tools:
        spec: ToolSpec = t.spec
        assert spec.readonly is True
        assert spec.cache is True


# ---------------------------------------------------------------------------
# Scoring + ranking
# ---------------------------------------------------------------------------


async def test_bm25_search_ranks_more_relevant_doc_higher(tmp_path: Path) -> None:
    _write_sidecar(
        tmp_path / "idx.json",
        [
            _entry("doc-a", "apple apple banana"),
            _entry("doc-b", "banana banana banana"),
            _entry("doc-c", "cherry"),
        ],
    )
    index = Bm25Index(path=tmp_path / "idx.json")
    bm25_search, _, _ = _funcs(index)
    result = await bm25_search(query="apple")
    assert [h["id"] for h in result["hits"]] == ["doc-a"]
    assert result["hits"][0]["score"] > 0
    assert result["total_matches"] == 1
    assert result["has_more"] is False


async def test_bm25_search_returns_self_describing_shape(tmp_path: Path) -> None:
    _write_sidecar(
        tmp_path / "idx.json",
        [
            _entry(
                "AAPL/2024",
                "research and development expenses were thirty billion dollars",
                identifiers={"entity_id": "AAPL", "year": "2024"},
                source="raw/AAPL/2024.pdf",
            ),
        ],
    )
    index = Bm25Index(path=tmp_path / "idx.json")
    bm25_search, _, _ = _funcs(index)
    result = await bm25_search(query="research")
    hit = result["hits"][0]
    assert hit["id"] == "AAPL/2024"
    assert hit["identifiers"] == {"entity_id": "AAPL", "year": "2024"}
    assert hit["source"] == "raw/AAPL/2024.pdf"
    assert "research" in hit["snippet"].lower()
    assert "has_more" in result and "truncated" in result and "total_matches" in result


async def test_bm25_search_top_k_caps_at_20_and_sets_has_more(tmp_path: Path) -> None:
    entries = [_entry(f"doc-{i:02d}", "apple") for i in range(25)]
    _write_sidecar(tmp_path / "idx.json", entries)
    index = Bm25Index(path=tmp_path / "idx.json")
    bm25_search, _, _ = _funcs(index)
    result = await bm25_search(query="apple", top_k=100)
    assert len(result["hits"]) == 20
    assert result["has_more"] is True
    assert result["total_matches"] == 25


async def test_bm25_search_zero_or_negative_top_k_uses_default(tmp_path: Path) -> None:
    entries = [_entry(f"doc-{i:02d}", "apple") for i in range(10)]
    _write_sidecar(tmp_path / "idx.json", entries)
    index = Bm25Index(path=tmp_path / "idx.json")
    bm25_search, _, _ = _funcs(index)
    result = await bm25_search(query="apple", top_k=0)
    assert len(result["hits"]) == 5


async def test_bm25_search_applies_filters(tmp_path: Path) -> None:
    _write_sidecar(
        tmp_path / "idx.json",
        [
            _entry("AAPL/2024", "apple growth", identifiers={"ticker": "AAPL"}),
            _entry("MSFT/2024", "apple growth", identifiers={"ticker": "MSFT"}),
        ],
    )
    index = Bm25Index(path=tmp_path / "idx.json")
    bm25_search, _, _ = _funcs(index)
    result = await bm25_search(query="apple", filters={"ticker": "AAPL"})
    assert [h["id"] for h in result["hits"]] == ["AAPL/2024"]


async def test_bm25_search_empty_query_raises(tmp_path: Path) -> None:
    _write_sidecar(tmp_path / "idx.json", [_entry("doc-a", "apple")])
    index = Bm25Index(path=tmp_path / "idx.json")
    bm25_search, _, _ = _funcs(index)
    with pytest.raises(ValueError):
        await bm25_search(query="   ")


async def test_bm25_search_no_matches_returns_empty_result(tmp_path: Path) -> None:
    _write_sidecar(tmp_path / "idx.json", [_entry("doc-a", "apple")])
    index = Bm25Index(path=tmp_path / "idx.json")
    bm25_search, _, _ = _funcs(index)
    result = await bm25_search(query="banana")
    assert result["hits"] == []
    assert result["total_matches"] == 0


# ---------------------------------------------------------------------------
# filtered_search
# ---------------------------------------------------------------------------


async def test_filtered_search_sorts_by_id_ascending(tmp_path: Path) -> None:
    _write_sidecar(
        tmp_path / "idx.json",
        [
            _entry("MSFT/2024", "...", identifiers={"ticker": "MSFT"}),
            _entry("AAPL/2024", "...", identifiers={"ticker": "AAPL"}),
            _entry("GOOG/2024", "...", identifiers={"ticker": "GOOG"}),
        ],
    )
    index = Bm25Index(path=tmp_path / "idx.json")
    _, filtered_search, _ = _funcs(index)
    result = await filtered_search(filters={})
    assert [h["id"] for h in result["hits"]] == ["AAPL/2024", "GOOG/2024", "MSFT/2024"]


async def test_filtered_search_with_list_filter_is_or_within_key(tmp_path: Path) -> None:
    _write_sidecar(
        tmp_path / "idx.json",
        [
            _entry("AAPL/2023", "...", identifiers={"year": "2023"}),
            _entry("AAPL/2024", "...", identifiers={"year": "2024"}),
            _entry("AAPL/2022", "...", identifiers={"year": "2022"}),
        ],
    )
    index = Bm25Index(path=tmp_path / "idx.json")
    _, filtered_search, _ = _funcs(index)
    result = await filtered_search(filters={"year": ["2023", "2024"]})
    assert [h["id"] for h in result["hits"]] == ["AAPL/2023", "AAPL/2024"]


# ---------------------------------------------------------------------------
# section_search
# ---------------------------------------------------------------------------


async def test_section_search_isolates_to_named_section(tmp_path: Path) -> None:
    _write_sidecar(
        tmp_path / "idx.json",
        [
            _entry(
                "AAPL/2024",
                "summary text here. risk text mentions litigation.",
                sections={
                    "document_summary": "summary text here",
                    "risk_factors": "litigation risks dominate this section",
                },
            ),
            _entry(
                "MSFT/2024",
                "summary mentions litigation. risks are minor.",
                sections={
                    "document_summary": "summary mentions litigation",
                    "risk_factors": "risks are minor",
                },
            ),
        ],
    )
    index = Bm25Index(path=tmp_path / "idx.json")
    _, _, section_search = _funcs(index)
    result = await section_search(query="litigation", section_name="risk_factors")
    assert [h["id"] for h in result["hits"]] == ["AAPL/2024"]


async def test_section_search_missing_section_returns_note(tmp_path: Path) -> None:
    _write_sidecar(
        tmp_path / "idx.json",
        [_entry("doc-a", "text", sections={"document_summary": "text"})],
    )
    index = Bm25Index(path=tmp_path / "idx.json")
    _, _, section_search = _funcs(index)
    result = await section_search(query="anything", section_name="risk_factors")
    assert result["hits"] == []
    assert "no entries have a section" in result["note"]


async def test_section_search_legacy_entry_without_sections_key(tmp_path: Path) -> None:
    # An entry written by an older Bm25IndexWriter (no sections field).
    _write_sidecar(
        tmp_path / "idx.json",
        [{"id": "doc-a", "identifiers": {}, "text": "litigation here", "source": ""}],
    )
    index = Bm25Index(path=tmp_path / "idx.json")
    _, _, section_search = _funcs(index)
    result = await section_search(query="litigation", section_name="risk_factors")
    assert result["hits"] == []
    assert "note" in result


async def test_section_search_empty_query_raises(tmp_path: Path) -> None:
    _write_sidecar(tmp_path / "idx.json", [_entry("doc-a", "x")])
    index = Bm25Index(path=tmp_path / "idx.json")
    _, _, section_search = _funcs(index)
    with pytest.raises(ValueError):
        await section_search(query="", section_name="document_summary")


# ---------------------------------------------------------------------------
# Degenerate sidecar paths
# ---------------------------------------------------------------------------


async def test_missing_sidecar_returns_note(tmp_path: Path) -> None:
    index = Bm25Index(path=tmp_path / "does-not-exist.json")
    bm25_search, filtered_search, section_search = _funcs(index)
    for result in (
        await bm25_search(query="anything"),
        await filtered_search(filters={}),
        await section_search(query="anything", section_name="x"),
    ):
        assert result["hits"] == []
        assert result["note"] == "index not built; run `reigner ingest`"


async def test_corrupt_sidecar_returns_note(tmp_path: Path) -> None:
    path = tmp_path / "idx.json"
    path.write_text("{ not json")
    index = Bm25Index(path=path)
    bm25_search, _, _ = _funcs(index)
    result = await bm25_search(query="anything")
    assert result["hits"] == []
    assert result["note"] == "index not built; run `reigner ingest`"


async def test_empty_list_sidecar_returns_note(tmp_path: Path) -> None:
    _write_sidecar(tmp_path / "idx.json", [])
    index = Bm25Index(path=tmp_path / "idx.json")
    bm25_search, _, _ = _funcs(index)
    result = await bm25_search(query="anything")
    assert result["hits"] == []
    assert result["note"] == "index not built; run `reigner ingest`"


async def test_non_list_sidecar_is_treated_as_empty(tmp_path: Path) -> None:
    path = tmp_path / "idx.json"
    path.write_text('{"id": "doc-a"}')  # valid JSON but wrong shape
    index = Bm25Index(path=path)
    bm25_search, _, _ = _funcs(index)
    result = await bm25_search(query="anything")
    assert result["hits"] == []
    assert result["note"] == "index not built; run `reigner ingest`"
