from __future__ import annotations

from pathlib import Path

from reigner.ingestion.loaders import JsonLoader


async def test_json_file_meta_marks_format(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_bytes(b'{"k": 1}')
    doc = await JsonLoader().load(path)
    assert doc.raw == b'{"k": 1}'
    assert doc.meta["format"] == "json"
    assert doc.meta["content_type"] == "application/json"
    assert "line_count" not in doc.meta


async def test_jsonl_file_records_line_count(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'{"a":1}\n{"a":2}\n\n{"a":3}\n')
    doc = await JsonLoader().load(path)
    assert doc.meta["format"] == "jsonl"
    assert doc.meta["content_type"] == "application/x-jsonlines"
    # blank line excluded
    assert doc.meta["line_count"] == 3


async def test_meta_extractor_merged_for_json(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_bytes(b"{}")
    doc = await JsonLoader(meta_extractor=lambda p: {"dataset": p.stem}).load(path)
    assert doc.meta["dataset"] == "data"
    assert doc.meta["format"] == "json"


async def test_extension_case_insensitive(tmp_path: Path) -> None:
    path = tmp_path / "DATA.JSONL"
    path.write_bytes(b'{"k":1}\n')
    doc = await JsonLoader().load(path)
    assert doc.meta["format"] == "jsonl"
