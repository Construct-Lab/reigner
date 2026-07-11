"""Behavior tests for `reigner init --recipe code_navigator`.

The code_navigator recipe is a sidecar over existing repos: it has no ingestion
step, so the scaffold is lean (no schema/extractors/library/search-index) and
wires ``tools.fs`` in multi-root mode.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reigner.cli.__main__ import app
from reigner.config import ReignerConfig
from reigner.harness.agent import Harness

# The lean scaffold — recipe files plus the shared env/gitignore, and nothing
# ingestion-shaped.
EXPECTED_PATHS = {
    "REIGNER.md",
    "reigner.yaml",
    "README.md",
    ".env.example",
    ".gitignore",
}

# Ingestion-shaped paths the sidecar recipe must NOT scaffold.
FORBIDDEN_PATHS = {
    "schema.yaml",
    "extractors",
    "extractors/my_extractor.py",
    "library",
    "library/raw",
    "library/artifacts",
    "search-index",
    "eval",
    "eval/cases.yaml",
}

runner = CliRunner()


def _run(args: list[str], cwd: Path):
    old = os.getcwd()
    os.chdir(cwd)
    try:
        return runner.invoke(app, args)
    finally:
        os.chdir(old)


def _feed_prompts(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    """Drive the interactive root prompts with a fixed sequence of answers."""
    it: Iterator[str] = iter(answers)
    monkeypatch.setattr("reigner.cli.init.RichPrompt.ask", lambda *a, **k: next(it))


def _present(target: Path) -> set[str]:
    return {p.relative_to(target).as_posix() for p in target.rglob("*")}


def test_recipe_scaffolds_lean_tree(tmp_path: Path) -> None:
    result = _run(["init", "demo", "--recipe", "code_navigator"], tmp_path)
    assert result.exit_code == 0, result.stdout + result.stderr
    present = _present(tmp_path / "demo")
    assert present >= EXPECTED_PATHS, f"missing: {EXPECTED_PATHS - present}"
    leaked = FORBIDDEN_PATHS & present
    assert not leaked, f"ingestion-shaped paths leaked into scaffold: {leaked}"


def test_recipe_readme_renders_project_name(tmp_path: Path) -> None:
    _run(["init", "demo", "--recipe", "code_navigator"], tmp_path)
    readme = (tmp_path / "demo" / "README.md").read_text()
    assert readme.startswith("# demo")
    assert "{project_name}" not in readme


def test_recipe_config_is_the_tuned_one(tmp_path: Path) -> None:
    _run(["init", "demo", "--recipe", "code_navigator"], tmp_path)
    cfg = ReignerConfig.load(tmp_path / "demo" / "reigner.yaml")
    assert cfg.name == "code_navigator"
    assert cfg.model.provider == "openai"
    # Multi-root fs, read-only, nothing ingestion-shaped.
    assert cfg.tools.fs is not None
    assert cfg.tools.fs.root is None
    assert set(cfg.tools.fs.roots or {}) == {"backend", "frontend"}
    assert cfg.tools.fs.write_enabled is False
    assert cfg.tools.artifacts is None
    assert cfg.tools.search is None
    assert cfg.oracle is None
    assert cfg.eval is None
    assert cfg.role.skills == []


def test_recipe_config_builds_a_harness(tmp_path: Path) -> None:
    _run(["init", "demo", "--recipe", "code_navigator"], tmp_path)
    # The placeholder roots resolve (relative to the config) to siblings of the
    # project dir; create them so build_fs_tools' existence check passes.
    (tmp_path / "path-to-backend").mkdir()
    (tmp_path / "path-to-frontend").mkdir()

    harness = Harness.from_config(tmp_path / "demo" / "reigner.yaml")
    names = {spec.name for spec in harness.registry}
    assert {"fs_read", "fs_grep", "fs_glob", "fs_ls"} <= names
    # Read-only default: no write tool, no oracle escalation.
    assert "fs_write" not in names
    assert "escalate_to_oracle" not in names
    assert harness.oracle_adapter is None


def test_interactive_roots_are_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # name, path, name, path, ... then an empty name to finish.
    _feed_prompts(monkeypatch, ["api", "../api", "web", "~/code/web", ""])
    _run(["init", "demo", "--recipe", "code_navigator"], tmp_path)

    cfg = ReignerConfig.load(tmp_path / "demo" / "reigner.yaml")
    assert cfg.tools.fs is not None
    assert cfg.tools.fs.roots == {"api": "../api", "web": "~/code/web"}
    # The surrounding config is preserved, not clobbered by the injection.
    assert cfg.tools.fs.write_enabled is False
    assert cfg.name == "code_navigator"


def test_interactive_supports_more_than_two_repos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _feed_prompts(
        monkeypatch,
        ["api", "../api", "web", "../web", "shared", "../shared", "infra", "../infra", ""],
    )
    _run(["init", "demo", "--recipe", "code_navigator"], tmp_path)

    cfg = ReignerConfig.load(tmp_path / "demo" / "reigner.yaml")
    assert set(cfg.tools.fs.roots or {}) == {"api", "web", "shared", "infra"}


def test_no_roots_entered_keeps_placeholder_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An empty first name finishes immediately — the bundled placeholders stay,
    # so the file is still a valid, editable template.
    _feed_prompts(monkeypatch, [""])
    result = _run(["init", "demo", "--recipe", "code_navigator"], tmp_path)
    assert result.exit_code == 0

    cfg = ReignerConfig.load(tmp_path / "demo" / "reigner.yaml")
    assert set(cfg.tools.fs.roots or {}) == {"backend", "frontend"}


def test_missing_root_fails_at_startup(tmp_path: Path) -> None:
    """A placeholder root left unedited fails loudly rather than silently."""
    from reigner.types import ConfigError

    _run(["init", "demo", "--recipe", "code_navigator"], tmp_path)
    # Roots point at ../path-to-backend etc., which do not exist.
    try:
        Harness.from_config(tmp_path / "demo" / "reigner.yaml")
    except ConfigError as exc:
        assert "tools.fs.roots" in str(exc)
    else:  # pragma: no cover - the check must fire
        raise AssertionError("expected ConfigError for unresolved placeholder root")
