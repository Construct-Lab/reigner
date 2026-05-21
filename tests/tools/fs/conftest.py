"""Shared fixtures for FS-tools tests.

Lays down a small repo-shaped tree under ``tmp_path/repo``:

    repo/
        README.md
        src/
            app.py          (contains "import os" and "TODO: needle")
            utils.py
        docs/
            guide.md
        .hidden/
            secret.md       (filtered by default)
        node_modules/
            pkg/index.js    (filtered by default)
        bin/
            blob.png        (binary suffix — fs_read rejects)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reigner.tools.fs import FsTools


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / ".hidden").mkdir()
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "bin").mkdir()

    (root / "README.md").write_text("# Repo\nThe needle is here.\n")
    (root / "src" / "app.py").write_text("import os\n# TODO: needle\nprint('hi')\n")
    (root / "src" / "utils.py").write_text("def helper():\n    return 1\n")
    (root / "docs" / "guide.md").write_text("guide text\nneedle in docs\n")
    (root / ".hidden" / "secret.md").write_text("needle in hidden\n")
    (root / "node_modules" / "pkg" / "index.js").write_text("// needle in node_modules\n")
    (root / "bin" / "blob.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return root


@pytest.fixture
def fs(repo: Path) -> FsTools:
    return FsTools(repo)


@pytest.fixture
def fs_write_enabled(repo: Path) -> FsTools:
    return FsTools(repo, write_enabled=True)
