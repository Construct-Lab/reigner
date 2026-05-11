from __future__ import annotations

import json

from reigner.artifacts.manifest import ExtractionMeta


def test_to_json_includes_all_fields() -> None:
    meta = ExtractionMeta(
        schema_version="1",
        identifiers={"ticker": "AAPL"},
        files=["metadata.json"],
        extractor={"source_hash": "abc"},
        written_at="2026-01-01T00:00:00+00:00",
    )
    payload = json.loads(meta.to_json())
    assert payload == {
        "schema_version": "1",
        "identifiers": {"ticker": "AAPL"},
        "files": ["metadata.json"],
        "extractor": {"source_hash": "abc"},
        "written_at": "2026-01-01T00:00:00+00:00",
    }


def test_round_trip() -> None:
    meta = ExtractionMeta(
        schema_version="1",
        identifiers={"ticker": "AAPL"},
        files=["a", "b"],
        extractor=None,
        written_at="2026-01-01T00:00:00+00:00",
    )
    restored = ExtractionMeta.from_json(meta.to_json())
    assert restored == meta


def test_writer_owned_fields_default() -> None:
    meta = ExtractionMeta(schema_version="1", identifiers={"a": "b"}, files=[])
    assert meta.extractor is None
    assert meta.written_at  # auto-populated
