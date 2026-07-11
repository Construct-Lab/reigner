"""Harness.from_config wires tools.fs to an FsTools backend.

Covers single-root and multi-root wiring plus the startup root-existence
check that build_fs_tools adds on top of the config-layer validation.
"""

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


def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "reigner.yaml"
    p.write_text(body)
    return p


def test_single_root_wires_read_only_tools(tmp_path: Path) -> None:
    (tmp_path / "sandbox").mkdir()
    body = MINIMAL + "tools:\n  fs:\n    root: ./sandbox\n"
    h = Harness.from_config(_write_yaml(tmp_path, body))
    names = {t.name for t in h.registry}
    assert {"fs_read", "fs_grep", "fs_glob", "fs_ls"} <= names
    assert "fs_write" not in names


def test_multi_root_wires_tools(tmp_path: Path) -> None:
    (tmp_path / "api").mkdir()
    (tmp_path / "web").mkdir()
    body = MINIMAL + "tools:\n  fs:\n    roots:\n      backend: ./api\n      frontend: ./web\n"
    h = Harness.from_config(_write_yaml(tmp_path, body))
    names = {t.name for t in h.registry}
    assert {"fs_read", "fs_grep", "fs_glob", "fs_ls"} <= names


def test_missing_single_root_fails_loudly(tmp_path: Path) -> None:
    body = MINIMAL + "tools:\n  fs:\n    root: ./does-not-exist\n"
    with pytest.raises(ConfigError, match="tools.fs.root does not exist"):
        Harness.from_config(_write_yaml(tmp_path, body))


def test_missing_one_of_several_roots_names_the_key(tmp_path: Path) -> None:
    (tmp_path / "api").mkdir()  # backend exists, frontend does not
    body = MINIMAL + "tools:\n  fs:\n    roots:\n      backend: ./api\n      frontend: ./web\n"
    with pytest.raises(ConfigError, match=r"tools.fs.roots\['frontend'\] does not exist"):
        Harness.from_config(_write_yaml(tmp_path, body))


def test_root_pointing_at_a_file_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("x")
    body = MINIMAL + "tools:\n  fs:\n    root: ./notes.txt\n"
    with pytest.raises(ConfigError, match="not a directory"):
        Harness.from_config(_write_yaml(tmp_path, body))
