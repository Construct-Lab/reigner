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
    # Four SPEC §6.4 builtins are auto-registered on every harness:
    # save_note, request_clarification, stop, register_citation.
    assert len(h.registry) == 4


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
    names = {t.name for t in h.registry}
    artifact_names = {
        "read_artifact_file",
        "grep_artifact",
        "get_json_field",
        "list_documents",
        "list_versions",
        "get_section",
    }
    assert artifact_names <= names
    assert all(t.readonly for t in h.registry if t.name in artifact_names)


def test_from_config_artifacts_missing_schema_raises_config_error(tmp_path: Path) -> None:
    body = (
        MINIMAL + "tools:\n  artifacts:\n    root: library/artifacts\n    schema: ./schema.yaml\n"
    )
    with pytest.raises(ConfigError, match="cannot load schema"):
        Harness.from_config(_write(tmp_path, body))


def test_from_config_search_unknown_type_raises_config_error(tmp_path: Path) -> None:
    (tmp_path / "idx.json").write_text("[]")
    body = MINIMAL + "tools:\n  search:\n    type: vector\n    index_path: idx.json\n"
    with pytest.raises(ConfigError, match="not supported"):
        Harness.from_config(_write(tmp_path, body))


def test_from_config_custom_tools_imported(tmp_path: Path) -> None:
    # Resolve a real @tool-decorated callable from a sibling test module —
    # the registry rejects non-decorated callables, so this probes both the
    # dotted-path resolution and that the result is a valid tool.
    body = MINIMAL + "tools:\n  custom:\n    - tests.fixtures.custom_tool:my_custom_tool\n"
    h = Harness.from_config(_write(tmp_path, body))
    assert "my_custom_tool" in h.registry


def test_from_config_settings_threaded_through(tmp_path: Path) -> None:
    body = MINIMAL + "settings:\n  max_iterations: 7\n  nudge_interval: 1\n"
    h = Harness.from_config(_write(tmp_path, body))
    assert h.settings.max_iterations == 7
    assert h.settings.nudge_interval == 1


def test_from_config_fs_wires_read_only_tools(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    body = MINIMAL + f"tools:\n  fs:\n    root: {sandbox.as_posix()}\n"
    h = Harness.from_config(_write(tmp_path, body))
    names = {t.name for t in h.registry}
    assert {"fs_read", "fs_grep", "fs_ls", "fs_glob"} <= names
    # write_enabled defaults to False — fs_write must stay out.
    assert "fs_write" not in names


def test_from_config_fs_write_enabled(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    body = MINIMAL + f"tools:\n  fs:\n    root: {sandbox.as_posix()}\n    write_enabled: true\n"
    h = Harness.from_config(_write(tmp_path, body))
    names = {t.name for t in h.registry}
    assert "fs_write" in names


def test_from_config_extra_tools_appended(tmp_path: Path) -> None:
    from reigner.tools.base import tool

    @tool(readonly=True)
    async def my_extra(x: int) -> dict:
        """An extra tool injected by the caller."""
        return {"x": x}

    h = Harness.from_config(_write(tmp_path, MINIMAL), tools=[my_extra])
    assert "my_extra" in h.registry
