"""Tests for ``Harness.from_config`` partial wiring (T-17 / issue #17)."""

from __future__ import annotations

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


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "reigner.yaml"
    p.write_text(body)
    return p


def test_from_config_builds_harness(tmp_path: Path) -> None:
    h = Harness.from_config(_write(tmp_path, MINIMAL))
    assert h.adapter.name == "openai"
    assert h.adapter.model == "gpt-4o"
    assert h.settings.max_iterations == 25
    assert h.role == ""
    assert h.tools == []


def test_from_config_loads_role_file(tmp_path: Path) -> None:
    (tmp_path / "REIGNER.md").write_text("you are an agent")
    h = Harness.from_config(_write(tmp_path, MINIMAL))
    assert h.role == "you are an agent"


def test_from_config_missing_role_file_is_empty_string(tmp_path: Path) -> None:
    h = Harness.from_config(_write(tmp_path, MINIMAL))
    # No REIGNER.md on disk → role is empty.
    assert h.role == ""


def test_from_config_oracle_adapter(tmp_path: Path) -> None:
    body = MINIMAL + "oracle:\n  provider: anthropic\n  model: claude-opus-4-7\n"
    h = Harness.from_config(_write(tmp_path, body))
    assert h.oracle_adapter is not None
    assert h.oracle_adapter.name == "anthropic"
    assert h.oracle_adapter.model == "claude-opus-4-7"


def test_from_config_artifacts_wires_six_tools(tmp_path: Path) -> None:
    (tmp_path / "schema.yaml").write_text(
        "entity_path: '{entity_id}/{version}'\n"
        "sections:\n  - document_summary\n  - sections/*\n"
        "json_artifacts:\n  - metadata.json\n"
    )
    body = (
        MINIMAL + "tools:\n  artifacts:\n    root: library/artifacts\n    schema: ./schema.yaml\n"
    )
    h = Harness.from_config(_write(tmp_path, body))
    names = {t.name for t in h.tools}
    assert names == {
        "read_artifact_file",
        "grep_artifact",
        "get_json_field",
        "list_documents",
        "list_versions",
        "get_section",
    }
    assert all(t.readonly for t in h.tools)


def test_from_config_artifacts_missing_schema_raises_config_error(tmp_path: Path) -> None:
    body = (
        MINIMAL + "tools:\n  artifacts:\n    root: library/artifacts\n    schema: ./schema.yaml\n"
    )
    with pytest.raises(ConfigError, match="cannot load schema"):
        Harness.from_config(_write(tmp_path, body))


def test_from_config_search_raises_with_helpful_message(tmp_path: Path) -> None:
    body = MINIMAL + "tools:\n  search:\n    type: bm25\n    index_path: idx.json\n"
    with pytest.raises(ConfigError, match="T-10"):
        Harness.from_config(_write(tmp_path, body))


def test_from_config_custom_tools_imported(tmp_path: Path) -> None:
    # Reach for an importable callable in the reigner package — we don't need
    # it to actually be a @tool, just to prove dotted-path resolution worked.
    body = MINIMAL + "tools:\n  custom:\n    - reigner.types:import_dotted\n"
    h = Harness.from_config(_write(tmp_path, body))
    from reigner.types import import_dotted

    assert h.tools == [import_dotted]


def test_from_config_settings_threaded_through(tmp_path: Path) -> None:
    body = MINIMAL + "settings:\n  max_iterations: 7\n  nudge_interval: 1\n"
    h = Harness.from_config(_write(tmp_path, body))
    assert h.settings.max_iterations == 7
    assert h.settings.nudge_interval == 1


def test_from_config_extra_tools_appended(tmp_path: Path) -> None:
    def my_tool() -> None:
        pass

    h = Harness.from_config(_write(tmp_path, MINIMAL), tools=[my_tool])  # type: ignore[list-item]
    assert h.tools == [my_tool]
