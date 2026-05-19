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
    assert "citation_strict" in result.output
    assert "T-31" in result.output  # deferral note


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


def test_inspect_tools_no_custom(project: Path) -> None:
    result = _run(["inspect", "tools"], project)
    assert result.exit_code == 0
    assert "no custom tools" in result.output


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
