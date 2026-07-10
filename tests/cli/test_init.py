"""Behavior tests for `reigner init` (T-18)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from reigner.cli.__main__ import app
from reigner.config import ReignerConfig

# Mirror SPEC §9.1 — the canonical list of paths blank mode produces.
EXPECTED_PATHS = {
    "REIGNER.md",
    "reigner.yaml",
    "schema.yaml",
    "extractors/__init__.py",
    "extractors/my_extractor.py",
    "extractors/pipeline.py",
    "library/raw",
    "library/artifacts",
    "search-index",
    "eval/cases.yaml",
    ".env.example",
    ".gitignore",
    "README.md",
}

runner = CliRunner()


def _run(args: list[str], cwd: Path):
    """Invoke the CLI with cwd set to a tmp dir — keeps scaffolding hermetic."""
    import os

    old = os.getcwd()
    os.chdir(cwd)
    try:
        return runner.invoke(app, args)
    finally:
        os.chdir(old)


def _present(target: Path) -> set[str]:
    out = set()
    for p in target.rglob("*"):
        rel = p.relative_to(target).as_posix()
        out.add(rel)
    return out


def test_blank_scaffolds_all_files(tmp_path: Path) -> None:
    result = _run(["init", "demo", "--blank"], tmp_path)
    assert result.exit_code == 0, result.stdout + result.stderr
    target = tmp_path / "demo"
    present = _present(target)
    missing = EXPECTED_PATHS - present
    assert not missing, f"missing scaffold paths: {missing}"


def test_pipeline_stub_includes_bm25_writer(tmp_path: Path) -> None:
    # SPEC §8.3 lists both writers; the stub must not silently drop the BM25
    # writer, or a freshly-init'd project never generates search-index/documents.json.
    _run(["init", "demo", "--blank"], tmp_path)
    stub = (tmp_path / "demo" / "extractors" / "pipeline.py").read_text()
    assert "Bm25IndexWriter" in stub
    assert "ArtifactWriter" in stub


def test_yaml_round_trips_through_config(tmp_path: Path) -> None:
    _run(["init", "demo", "--blank"], tmp_path)
    # Must validate without raising — catches drift from ReignerConfig schema.
    cfg = ReignerConfig.load(tmp_path / "demo" / "reigner.yaml")
    assert cfg.name == "demo"


def test_collision_refuses_without_force(tmp_path: Path) -> None:
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "stray.txt").write_text("user data")
    result = _run(["init", "demo", "--blank"], tmp_path)
    assert result.exit_code == 1
    assert "already exists" in result.stderr
    # Non-empty target left untouched.
    assert (tmp_path / "demo" / "stray.txt").read_text() == "user data"


def test_force_overwrites_scaffold_keeps_foreign(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    target.mkdir()
    (target / "REIGNER.md").write_text("OLD CONTENT")
    (target / "notes.txt").write_text("keep me")

    result = _run(["init", "demo", "--blank", "--force"], tmp_path)
    assert result.exit_code == 0, result.stdout + result.stderr

    # Scaffold file overwritten…
    assert (target / "REIGNER.md").read_text() != "OLD CONTENT"
    # …but foreign user file untouched.
    assert (target / "notes.txt").read_text() == "keep me"


# `--recipe` behavior is covered in test_init_recipe.py.
# Guided is the default mode; its behavior is covered in test_init_guided.py.


@pytest.mark.parametrize("bad", ["1abc", "my/agent", "my agent", "with.dot"])
def test_invalid_names_rejected(tmp_path: Path, bad: str) -> None:
    result = _run(["init", bad, "--blank"], tmp_path)
    assert result.exit_code == 2
    assert "invalid project name" in result.stderr
    assert not (tmp_path / bad).exists()


def test_two_mode_flags_rejected(tmp_path: Path) -> None:
    result = _run(["init", "demo", "--blank", "--recipe", "document_qa"], tmp_path)
    assert result.exit_code == 2
    assert "at most one" in result.stderr


def test_version_still_works() -> None:
    """_meta.register kept the existing `version` command alive."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip()  # some non-empty version string
