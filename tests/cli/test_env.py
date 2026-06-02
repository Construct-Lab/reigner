"""Behavior tests for ``reigner.cli._env.load_project_env``.

Four contracts, one each:
  1. A key in ``<root>/.env`` lands in ``os.environ``.
  2. Real OS env wins — ``override=False`` never clobbers an existing value.
  3. A missing ``.env`` is a silent no-op returning ``False``.
  4. ``config_path=None`` resolves the root from the current working directory.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from reigner.cli._env import load_project_env


def _write_env(root: Path, body: str) -> Path:
    env = root / ".env"
    env.write_text(body)
    return env


def test_loads_key_from_env_beside_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REIGNER_TEST_KEY", raising=False)
    _write_env(tmp_path, "REIGNER_TEST_KEY=from-dotenv\n")
    config_path = tmp_path / "reigner.yaml"

    loaded = load_project_env(config_path)

    assert loaded is True
    assert os.environ["REIGNER_TEST_KEY"] == "from-dotenv"


def test_real_os_env_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REIGNER_TEST_KEY", "from-shell")
    _write_env(tmp_path, "REIGNER_TEST_KEY=from-dotenv\n")

    load_project_env(tmp_path / "reigner.yaml")

    assert os.environ["REIGNER_TEST_KEY"] == "from-shell"


def test_missing_env_is_silent_noop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # tmp_path has no .env file.
    loaded = load_project_env(tmp_path / "reigner.yaml")

    assert loaded is False
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_none_config_path_falls_back_to_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("REIGNER_TEST_KEY", raising=False)
    _write_env(tmp_path, "REIGNER_TEST_KEY=from-cwd\n")
    monkeypatch.chdir(tmp_path)

    loaded = load_project_env()

    assert loaded is True
    assert os.environ["REIGNER_TEST_KEY"] == "from-cwd"
