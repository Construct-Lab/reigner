"""FsTools — trust boundary and tool assembly."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from reigner.tools.fs import FsTools


def test_resolve_accepts_relative_path(fs: FsTools, repo: Path) -> None:
    assert fs.resolve("src/app.py") == repo / "src" / "app.py"


def test_resolve_rejects_absolute_path(fs: FsTools) -> None:
    with pytest.raises(ValueError, match="must be relative"):
        fs.resolve("/etc/passwd")


def test_resolve_rejects_empty(fs: FsTools) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        fs.resolve("")


def test_resolve_rejects_traversal_escape(fs: FsTools) -> None:
    with pytest.raises(ValueError, match="escapes fs root"):
        fs.resolve("../outside.txt")


def test_resolve_rejects_traversal_via_subdir(fs: FsTools) -> None:
    with pytest.raises(ValueError, match="escapes fs root"):
        fs.resolve("src/../../outside.txt")


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks require admin on Windows")
def test_resolve_rejects_symlink_pointing_outside(fs: FsTools, repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("nope")
    link = repo / "escape.txt"
    os.symlink(outside, link)
    with pytest.raises(ValueError, match="escapes fs root"):
        fs.resolve("escape.txt")


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks require admin on Windows")
def test_resolve_follows_in_root_symlink(fs: FsTools, repo: Path) -> None:
    target = repo / "src" / "app.py"
    link = repo / "link.py"
    os.symlink(target, link)
    resolved = fs.resolve("link.py")
    assert resolved == target.resolve()


def test_tools_default_omits_fs_write(fs: FsTools) -> None:
    names = {t.name for t in fs.tools()}
    assert names == {"fs_read", "fs_grep", "fs_glob", "fs_ls"}


def test_tools_write_enabled_includes_fs_write(fs_write_enabled: FsTools) -> None:
    names = {t.name for t in fs_write_enabled.tools()}
    assert names == {"fs_read", "fs_grep", "fs_glob", "fs_ls", "fs_write"}


def test_readonly_flags(fs_write_enabled: FsTools) -> None:
    by_name = {t.name: t for t in fs_write_enabled.tools()}
    for name in ("fs_read", "fs_grep", "fs_glob", "fs_ls"):
        assert by_name[name].readonly is True, name
    assert by_name["fs_write"].readonly is False


def test_is_ignored_filters_ignored_dirs(fs: FsTools, repo: Path) -> None:
    assert fs.is_ignored(repo / "node_modules" / "pkg" / "index.js")
    assert fs.is_ignored(repo / ".hidden" / "secret.md")
    assert not fs.is_ignored(repo / "src" / "app.py")


def test_is_ignored_include_hidden_keeps_dotfiles(fs: FsTools, repo: Path) -> None:
    assert not fs.is_ignored(repo / ".hidden" / "secret.md", include_hidden=True)
    # node_modules is in ignored_dirs even when include_hidden=True
    assert fs.is_ignored(repo / "node_modules" / "pkg" / "index.js", include_hidden=True)
