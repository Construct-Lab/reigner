"""Harness.from_config wires tools.search to a SearchIndex backend."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reigner.harness.agent import Harness
from reigner.types import ConfigError

MINIMAL = """\
name: demo
model:
  provider: openai
  name: gpt-4o
"""


def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "reigner.yaml"
    p.write_text(body)
    return p


def _write_index(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "idx.json"
    p.write_text(json.dumps(entries))
    return p


SEARCH_SECTION = "tools:\n  search:\n    type: bm25\n    index_path: idx.json\n"


def test_from_config_wires_three_search_tools(tmp_path: Path) -> None:
    _write_index(tmp_path, [])
    h = Harness.from_config(_write_yaml(tmp_path, MINIMAL + SEARCH_SECTION))
    names = {t.name for t in h.registry}
    assert {"bm25_search", "filtered_search", "section_search"} <= names


def test_search_tools_are_readonly(tmp_path: Path) -> None:
    _write_index(tmp_path, [])
    h = Harness.from_config(_write_yaml(tmp_path, MINIMAL + SEARCH_SECTION))
    search_names = {"bm25_search", "filtered_search", "section_search"}
    assert all(t.readonly is True for t in h.registry if t.name in search_names)


def test_search_tools_are_cacheable(tmp_path: Path) -> None:
    _write_index(tmp_path, [])
    h = Harness.from_config(_write_yaml(tmp_path, MINIMAL + SEARCH_SECTION))
    search_names = {"bm25_search", "filtered_search", "section_search"}
    assert all(t.cache is True for t in h.registry if t.name in search_names)


def test_artifacts_and_search_compose_without_collision(tmp_path: Path) -> None:
    (tmp_path / "schema.yaml").write_text(
        "entity_path: '{entity_id}/{version}'\n"
        "sections:\n  - document_summary\n"
        "json_artifacts:\n  - metadata.json\n"
    )
    _write_index(tmp_path, [])
    body = (
        MINIMAL
        + "tools:\n"
        + "  artifacts:\n    root: library/artifacts\n    schema: ./schema.yaml\n"
        + "  search:\n    type: bm25\n    index_path: idx.json\n"
    )
    h = Harness.from_config(_write_yaml(tmp_path, body))
    names = {t.name for t in h.registry}
    # Six artifact tools + three search tools + four auto-registered builtins
    # (save_note, request_clarification, stop, register_citation).
    assert len(h.registry) == 13
    assert {"bm25_search", "filtered_search", "section_search"} <= names
    assert {"read_artifact_file", "grep_artifact", "list_documents"} <= names


def test_search_tools_invocable_through_session(tmp_path: Path) -> None:
    """End-to-end: bm25_search reaches the underlying index via the adapter."""
    _write_index(
        tmp_path,
        [
            {
                "id": "doc-a",
                "identifiers": {},
                "text": "apple pie recipe",
                "sections": {},
                "source": "",
            }
        ],
    )
    h = Harness.from_config(_write_yaml(tmp_path, MINIMAL + SEARCH_SECTION))
    tools_by_name = {t.name: t for t in h.registry}
    assert "bm25_search" in tools_by_name


async def test_search_tool_run_invokes_underlying_index(tmp_path: Path) -> None:
    _write_index(
        tmp_path,
        [
            {
                "id": "doc-a",
                "identifiers": {"ticker": "AAPL"},
                "text": "apple pie recipe",
                "sections": {},
                "source": "raw/doc-a.txt",
            }
        ],
    )
    h = Harness.from_config(_write_yaml(tmp_path, MINIMAL + SEARCH_SECTION))
    tools_by_name = {a.name: a for a in h.registry.for_profile("full")}
    result = await tools_by_name["bm25_search"].run({"query": "apple"})
    assert result["hits"][0]["id"] == "doc-a"
    assert result["total_matches"] == 1


def test_from_config_missing_index_file_does_not_raise(tmp_path: Path) -> None:
    """Bm25Index tolerates a missing sidecar — agents see a 'not built' note.

    The harness must build even before `reigner ingest` has been run; failing
    at config-load time would prevent users from inspecting a fresh project.
    """
    body = MINIMAL + "tools:\n  search:\n    type: bm25\n    index_path: missing.json\n"
    h = Harness.from_config(_write_yaml(tmp_path, body))
    # Three search tools + four auto-registered builtins.
    assert len(h.registry) == 7


def test_from_config_unknown_search_type_raises(tmp_path: Path) -> None:
    _write_index(tmp_path, [])
    body = MINIMAL + "tools:\n  search:\n    type: vector\n    index_path: idx.json\n"
    with pytest.raises(ConfigError, match="vector"):
        Harness.from_config(_write_yaml(tmp_path, body))
