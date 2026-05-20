from __future__ import annotations

import json
from pathlib import Path

from reigner.ingestion.loaders import LoadedDocument
from reigner.ingestion.results import ExtractionResult
from reigner.ingestion.writers import Bm25IndexWriter


def _doc(source: str = "data/raw/AAPL_2024.pdf") -> LoadedDocument:
    return LoadedDocument(raw=b"_", meta={"source": source})


def _result(text: str = "hello") -> ExtractionResult:
    return ExtractionResult(sections={"document_summary": text}, json_artifacts={}, meta={})


async def test_writes_atomic_json_list(tmp_path: Path) -> None:
    writer = Bm25IndexWriter(path=tmp_path / "idx.json")
    await writer.write(
        loaded=_doc(),
        result=_result("apple"),
        identifiers={"ticker": "AAPL", "fiscal_year": "2024"},
    )
    data = json.loads((tmp_path / "idx.json").read_text())
    assert isinstance(data, list) and len(data) == 1
    entry = data[0]
    assert entry["id"] == "2024/AAPL"  # sorted by identifier key
    assert entry["identifiers"] == {"ticker": "AAPL", "fiscal_year": "2024"}
    assert entry["text"] == "apple"
    assert entry["sections"] == {"document_summary": "apple"}
    assert entry["source"] == "data/raw/AAPL_2024.pdf"
    # tmp file cleaned up
    assert not (tmp_path / "idx.json.tmp").exists()


async def test_concatenates_sections_with_blank_lines(tmp_path: Path) -> None:
    writer = Bm25IndexWriter(path=tmp_path / "idx.json")
    result = ExtractionResult(
        sections={"document_summary": "summary", "sections/risks": "risks"},
        json_artifacts={},
        meta={},
    )
    await writer.write(loaded=_doc(), result=result, identifiers={"id": "X"})
    entry = json.loads((tmp_path / "idx.json").read_text())[0]
    assert "summary" in entry["text"] and "risks" in entry["text"]
    assert "\n\n" in entry["text"]
    assert entry["sections"] == {
        "document_summary": "summary",
        "sections/risks": "risks",
    }


async def test_upsert_replaces_existing_entry(tmp_path: Path) -> None:
    writer = Bm25IndexWriter(path=tmp_path / "idx.json")
    ids = {"ticker": "AAPL", "fiscal_year": "2024"}
    await writer.write(loaded=_doc(), result=_result("v1"), identifiers=ids)
    await writer.write(loaded=_doc(), result=_result("v2"), identifiers=ids)
    data = json.loads((tmp_path / "idx.json").read_text())
    assert len(data) == 1
    assert data[0]["text"] == "v2"


async def test_multiple_entities_sorted_by_id(tmp_path: Path) -> None:
    writer = Bm25IndexWriter(path=tmp_path / "idx.json")
    await writer.write(loaded=_doc(), result=_result("m"), identifiers={"k": "MSFT"})
    await writer.write(loaded=_doc(), result=_result("a"), identifiers={"k": "AAPL"})
    data = json.loads((tmp_path / "idx.json").read_text())
    assert [e["id"] for e in data] == ["AAPL", "MSFT"]


async def test_falls_back_to_url_meta_when_no_source(tmp_path: Path) -> None:
    writer = Bm25IndexWriter(path=tmp_path / "idx.json")
    doc = LoadedDocument(raw=b"_", meta={"url": "https://example.test/x"})
    await writer.write(loaded=doc, result=_result(), identifiers={"k": "X"})
    entry = json.loads((tmp_path / "idx.json").read_text())[0]
    assert entry["source"] == "https://example.test/x"


async def test_corrupt_sidecar_is_replaced_not_crashed(tmp_path: Path) -> None:
    path = tmp_path / "idx.json"
    path.write_text("{ not json")
    writer = Bm25IndexWriter(path=path)
    await writer.write(loaded=_doc(), result=_result("ok"), identifiers={"k": "X"})
    data = json.loads(path.read_text())
    assert len(data) == 1 and data[0]["text"] == "ok"


async def test_empty_identifiers_yields_empty_id(tmp_path: Path) -> None:
    writer = Bm25IndexWriter(path=tmp_path / "idx.json")
    await writer.write(loaded=_doc(), result=_result(), identifiers={})
    entry = json.loads((tmp_path / "idx.json").read_text())[0]
    assert entry["id"] == ""
