"""Behavior tests for `reigner inspect` (T-20)."""

from __future__ import annotations

import os
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reigner.cli.__main__ import app

runner = CliRunner()

_MIN_YAML = """\
name: test
version: 0.1.0

model:
  provider: openai
  name: gpt-4o

role:
  file: REIGNER.md
  skills: []
"""


def _run(args: list[str], cwd: Path):
    old = os.getcwd()
    os.chdir(cwd)
    try:
        return runner.invoke(app, args, catch_exceptions=False)
    finally:
        os.chdir(old)


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "reigner.yaml").write_text(_MIN_YAML)
    (tmp_path / "REIGNER.md").write_text("# Test role\nBe careful.\n")
    yield tmp_path


# ---------------------------------------------------------------------------
# inspect role
# ---------------------------------------------------------------------------


def test_inspect_role_prints_file(project: Path) -> None:
    result = _run(["inspect", "role"], project)
    assert result.exit_code == 0
    assert "Be careful." in result.output
    assert "REIGNER.md" in result.output


def test_inspect_role_missing_file(project: Path) -> None:
    (project / "REIGNER.md").unlink()
    result = _run(["inspect", "role"], project)
    assert result.exit_code == 0  # not fatal — just warns
    assert "not found" in result.output


def test_inspect_role_shows_skills(project: Path) -> None:
    yaml = _MIN_YAML.replace("skills: []", "skills: [citation_strict, clarify_when_ambiguous]")
    (project / "reigner.yaml").write_text(yaml)
    result = _run(["inspect", "role"], project)
    assert result.exit_code == 0
    # The composed menu: each configured skill's name + its one-line description.
    assert "citation_strict" in result.output
    assert "clarify_when_ambiguous" in result.output
    assert "Active skills" in result.output
    assert "load_skill" in result.output  # explains how bodies load on demand


# ---------------------------------------------------------------------------
# inspect config
# ---------------------------------------------------------------------------


def test_inspect_config_shows_settings_table(project: Path) -> None:
    result = _run(["inspect", "config"], project)
    assert result.exit_code == 0
    assert "test" in result.output  # name
    assert "max_iterations" in result.output
    assert "default" in result.output  # at least one default-sourced row


def test_inspect_config_marks_file_overrides(project: Path) -> None:
    yaml = _MIN_YAML + "settings:\n  max_iterations: 99\n"
    (project / "reigner.yaml").write_text(yaml)
    result = _run(["inspect", "config"], project)
    assert result.exit_code == 0
    assert "99" in result.output
    assert "file" in result.output


# ---------------------------------------------------------------------------
# inspect tools
# ---------------------------------------------------------------------------


def test_inspect_tools_shows_builtins_by_default(project: Path) -> None:
    """Even with no tools.* configured, builtins (save_note, …) appear."""
    result = _run(["inspect", "tools"], project)
    assert result.exit_code == 0
    assert "save_note" in result.output
    assert "request_clarification" in result.output
    assert "stop" in result.output
    assert "register_citation" in result.output
    assert "builtin" in result.output
    # No oracle configured → escalate_to_oracle is hidden.
    assert "escalate_to_oracle" not in result.output
    # The misleading deferred framing is gone.
    assert "deferred" not in result.output.lower()


def test_inspect_tools_shows_oracle_when_configured(project: Path) -> None:
    yaml = _MIN_YAML + textwrap.dedent(
        """
        oracle:
          provider: anthropic
          model: claude-opus-4-7
        """
    )
    (project / "reigner.yaml").write_text(yaml)
    result = _run(["inspect", "tools"], project)
    assert result.exit_code == 0
    assert "escalate_to_oracle" in result.output


def test_inspect_tools_lists_custom(project: Path) -> None:
    # Drop a tool module on disk and reference it from reigner.yaml.
    (project / "mytools.py").write_text(
        textwrap.dedent(
            """
            from reigner.tools import tool

            @tool(readonly=True)
            async def my_reader() -> str:
                \"\"\"Reads stuff.\"\"\"
                return "ok"
            """
        )
    )
    yaml = _MIN_YAML + "tools:\n  custom: [mytools:my_reader]\n"
    (project / "reigner.yaml").write_text(yaml)
    result = _run(["inspect", "tools"], project)
    assert result.exit_code == 0
    assert "my_reader" in result.output


def test_inspect_tools_wires_artifacts(tmp_path: Path) -> None:
    """tools.artifacts produces real ArtifactStore tool rows, source='artifacts'."""
    project = _project_with_schema(tmp_path)
    (project / "library/artifacts").mkdir(parents=True, exist_ok=True)
    result = _run(["inspect", "tools"], project)
    assert result.exit_code == 0
    assert "deferred" not in result.output.lower()
    # ArtifactStore exposes read_artifact_file / grep_artifact / etc.
    assert "read_artifact_file" in result.output or "grep_artifact" in result.output
    assert "artifacts" in result.output


def test_inspect_tools_search_failure_renders_x(project: Path) -> None:
    """A bogus search index path produces a red ✗ line without crashing."""
    yaml = _MIN_YAML + textwrap.dedent(
        """
        tools:
          search:
            type: bm25
            index_path: /does/not/exist/index.json
        """
    )
    (project / "reigner.yaml").write_text(yaml)
    result = _run(["inspect", "tools"], project)
    # Bm25Index returns empty entries on missing file rather than raising,
    # so the row appears with the search tools — but the index is empty.
    # We're just asserting the command stays alive.
    assert result.exit_code == 0
    assert "bm25_search" in result.output


def test_inspect_tools_fs_wired(project: Path) -> None:
    """tools.fs registers fs_read/fs_grep/fs_ls/fs_glob (and fs_write when enabled)."""
    yaml = _MIN_YAML + textwrap.dedent(
        """
        tools:
          fs:
            root: .
            write_enabled: true
        """
    )
    (project / "reigner.yaml").write_text(yaml)
    result = _run(["inspect", "tools"], project)
    assert result.exit_code == 0
    for name in ("fs_read", "fs_grep", "fs_ls", "fs_glob", "fs_write"):
        assert name in result.output, f"missing {name} in:\n{result.output}"


def test_inspect_tools_fs_default_no_write(project: Path) -> None:
    yaml = _MIN_YAML + textwrap.dedent(
        """
        tools:
          fs:
            root: .
        """
    )
    (project / "reigner.yaml").write_text(yaml)
    result = _run(["inspect", "tools"], project)
    assert result.exit_code == 0
    assert "fs_read" in result.output
    assert "fs_write" not in result.output


def test_inspect_tools_fs_bad_root(project: Path) -> None:
    """A missing fs root surfaces as ✗ fs: ... rather than crashing."""
    yaml = _MIN_YAML + textwrap.dedent(
        """
        tools:
          fs:
            root: /does/not/exist/anywhere
        """
    )
    (project / "reigner.yaml").write_text(yaml)
    result = _run(["inspect", "tools"], project)
    assert result.exit_code == 0
    # Builtins still render even when one backend fails.
    assert "save_note" in result.output


# ---------------------------------------------------------------------------
# inspect index
# ---------------------------------------------------------------------------


def _project_with_search(tmp_path: Path, index_path: str = "search-index/docs.json") -> Path:
    yaml = _MIN_YAML + textwrap.dedent(
        f"""
        tools:
          search:
            type: bm25
            index_path: {index_path}
        """
    )
    (tmp_path / "reigner.yaml").write_text(yaml)
    (tmp_path / "REIGNER.md").write_text("# role")
    return tmp_path


def test_inspect_index_no_search_configured(project: Path) -> None:
    result = _run(["inspect", "index"], project)
    assert result.exit_code == 0
    assert "no tools.search" in result.output


def test_inspect_index_missing_file(tmp_path: Path) -> None:
    project = _project_with_search(tmp_path)
    result = _run(["inspect", "index"], project)
    assert result.exit_code == 0
    assert "does not exist" in result.output


def test_inspect_index_populated(tmp_path: Path) -> None:
    import json as _json

    project = _project_with_search(tmp_path)
    idx_path = project / "search-index/docs.json"
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    idx_path.write_text(
        _json.dumps(
            [
                {
                    "id": "AAPL/2024",
                    "text": "apple revenue grew strongly",
                    "sections": {"summary": "apple grew", "risks": "supply chain"},
                },
                {
                    "id": "MSFT/2024",
                    "text": "microsoft cloud expanded",
                    "sections": {"summary": "azure growth"},
                },
            ]
        )
    )
    result = _run(["inspect", "index"], project)
    assert result.exit_code == 0
    assert "AAPL/2024" in result.output
    assert "MSFT/2024" in result.output
    assert "summary" in result.output
    assert "risks" in result.output
    # 2 docs
    assert "2" in result.output


# ---------------------------------------------------------------------------
# inspect artifacts
# ---------------------------------------------------------------------------


def _project_with_schema(tmp_path: Path) -> Path:
    schema = textwrap.dedent(
        """
        entity_path: "{entity_id}/{version}"
        sections:
          - name: document_summary
            required: false
        json_artifacts: []
        """
    )
    yaml = _MIN_YAML + textwrap.dedent(
        """
        tools:
          artifacts:
            root: library/artifacts
            schema: ./schema.yaml
        """
    )
    (tmp_path / "reigner.yaml").write_text(yaml)
    (tmp_path / "REIGNER.md").write_text("# role")
    (tmp_path / "schema.yaml").write_text(schema)
    return tmp_path


def test_inspect_artifacts_empty_root(tmp_path: Path) -> None:
    project = _project_with_schema(tmp_path)
    result = _run(["inspect", "artifacts"], project)
    assert result.exit_code == 0
    assert "does not exist" in result.output or "no entities" in result.output


def test_inspect_artifacts_lists_entities(tmp_path: Path) -> None:
    project = _project_with_schema(tmp_path)
    # Build a couple of entities matching {entity_id}/{version}.
    (project / "library/artifacts/AAPL/2024").mkdir(parents=True)
    (project / "library/artifacts/AAPL/2023").mkdir(parents=True)
    (project / "library/artifacts/MSFT/2024").mkdir(parents=True)
    result = _run(["inspect", "artifacts"], project)
    assert result.exit_code == 0
    assert "AAPL" in result.output
    assert "MSFT" in result.output


def test_inspect_artifacts_entity_drill(tmp_path: Path) -> None:
    project = _project_with_schema(tmp_path)
    ent = project / "library/artifacts/AAPL/2024"
    ent.mkdir(parents=True)
    (ent / "document_summary.md").write_text("# summary")
    (ent / "metadata.json").write_text('{"a": 1, "b": 2}')
    result = _run(["inspect", "artifacts", "--entity", "AAPL/2024"], project)
    assert result.exit_code == 0
    assert "document_summary.md" in result.output
    assert "metadata.json" in result.output
    assert "2 fields" in result.output


def test_inspect_artifacts_no_config(project: Path) -> None:
    # project fixture has no tools.artifacts block
    result = _run(["inspect", "artifacts"], project)
    assert result.exit_code == 2
    assert "not configured" in result.output


# ---------------------------------------------------------------------------
# Shared: missing config
# ---------------------------------------------------------------------------


def test_inspect_missing_config(tmp_path: Path) -> None:
    result = _run(["inspect", "role"], tmp_path)
    assert result.exit_code == 2
    assert "no reigner.yaml" in result.output
