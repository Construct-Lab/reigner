"""Per-tool behavior tests for the FS tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from reigner.tools.fs import FsTools
from reigner.tools.fs.glob import build_fs_glob
from reigner.tools.fs.grep import build_fs_grep
from reigner.tools.fs.ls import build_fs_ls
from reigner.tools.fs.read import build_fs_read
from reigner.tools.fs.write import build_fs_write

# ---- fs_read ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_returns_full_small_file(fs: FsTools) -> None:
    read = build_fs_read(fs)
    res = await read(path="src/app.py")
    assert "import os" in res["content"]
    assert res["offset"] == 0
    assert res["has_more"] is False
    assert res["total_size"] == len(res["content"])


@pytest.mark.asyncio
async def test_read_paginates(fs: FsTools) -> None:
    read = build_fs_read(fs)
    res = await read(path="src/app.py", offset=0, limit=5)
    assert len(res["content"]) == 5
    assert res["has_more"] is True


@pytest.mark.asyncio
async def test_read_rejects_binary_suffix(fs: FsTools) -> None:
    read = build_fs_read(fs)
    with pytest.raises(ValueError, match="not a readable text file"):
        await read(path="bin/blob.png")


@pytest.mark.asyncio
async def test_read_caps_limit_to_max(fs: FsTools, repo: Path) -> None:
    big = "x" * 50_000
    (repo / "big.txt").write_text(big)
    fs.max_read_chars = 100
    read = build_fs_read(fs)
    res = await read(path="big.txt", limit=10_000)
    assert res["limit"] == 100
    assert len(res["content"]) == 100
    assert res["has_more"] is True


@pytest.mark.asyncio
async def test_read_missing_raises(fs: FsTools) -> None:
    read = build_fs_read(fs)
    with pytest.raises(FileNotFoundError):
        await read(path="src/missing.py")


# ---- fs_ls -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_ls_root_filters_hidden_and_ignored(fs: FsTools) -> None:
    ls = build_fs_ls(fs)
    res = await ls(path=".")
    names = {e["name"] for e in res["entries"]}
    assert "README.md" in names
    assert "src" in names
    assert ".hidden" not in names
    assert "node_modules" not in names


@pytest.mark.asyncio
async def test_ls_include_hidden_shows_dotfiles_but_not_ignored(fs: FsTools) -> None:
    ls = build_fs_ls(fs)
    res = await ls(path=".", include_hidden=True)
    names = {e["name"] for e in res["entries"]}
    assert ".hidden" in names
    assert "node_modules" not in names  # still filtered by ignored_dirs


@pytest.mark.asyncio
async def test_ls_subdir_returns_types(fs: FsTools) -> None:
    ls = build_fs_ls(fs)
    res = await ls(path="src")
    by_name = {e["name"]: e for e in res["entries"]}
    assert by_name["app.py"]["type"] == "file"
    assert by_name["app.py"]["size"] is not None
    assert by_name["app.py"]["size"] > 0


@pytest.mark.asyncio
async def test_ls_cap_truncates(fs: FsTools, repo: Path) -> None:
    for i in range(10):
        (repo / "src" / f"f{i}.py").write_text("x")
    fs.max_ls_entries = 5
    ls = build_fs_ls(fs)
    res = await ls(path="src")
    assert res["truncated"] is True
    assert res["count"] == 5


@pytest.mark.asyncio
async def test_ls_rejects_file_path(fs: FsTools) -> None:
    ls = build_fs_ls(fs)
    with pytest.raises(NotADirectoryError):
        await ls(path="src/app.py")


# ---- fs_glob ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_glob_recursive_python(fs: FsTools) -> None:
    glob = build_fs_glob(fs)
    res = await glob(pattern="**/*.py")
    assert "src/app.py" in res["paths"]
    assert "src/utils.py" in res["paths"]


@pytest.mark.asyncio
async def test_glob_filters_ignored_dirs(fs: FsTools) -> None:
    glob = build_fs_glob(fs)
    res = await glob(pattern="**/*.js")
    # node_modules/pkg/index.js is the only .js — should be filtered
    assert res["paths"] == []


@pytest.mark.asyncio
async def test_glob_filters_hidden_by_default(fs: FsTools) -> None:
    glob = build_fs_glob(fs)
    res = await glob(pattern="**/*.md")
    assert "README.md" in res["paths"]
    assert "docs/guide.md" in res["paths"]
    assert not any(".hidden" in p for p in res["paths"])


@pytest.mark.asyncio
async def test_glob_relative_base(fs: FsTools) -> None:
    glob = build_fs_glob(fs)
    res = await glob(pattern="*.py", base="src")
    assert "src/app.py" in res["paths"]


@pytest.mark.asyncio
async def test_glob_rejects_absolute_pattern(fs: FsTools) -> None:
    glob = build_fs_glob(fs)
    with pytest.raises(ValueError, match="must be relative"):
        await glob(pattern="/etc/*")


@pytest.mark.asyncio
async def test_glob_cap_truncates(fs: FsTools, repo: Path) -> None:
    for i in range(10):
        (repo / "src" / f"g{i}.py").write_text("x")
    fs.max_glob_results = 4
    glob = build_fs_glob(fs)
    res = await glob(pattern="**/*.py")
    assert res["truncated"] is True
    assert len(res["paths"]) == 4


# ---- fs_grep ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_grep_finds_literal_across_files(fs: FsTools) -> None:
    grep = build_fs_grep(fs)
    res = await grep(query="needle")
    rels = {m["path"] for m in res["matches"]}
    assert "README.md" in rels
    assert "src/app.py" in rels
    assert "docs/guide.md" in rels


@pytest.mark.asyncio
async def test_grep_skips_ignored_dirs(fs: FsTools) -> None:
    grep = build_fs_grep(fs)
    res = await grep(query="needle")
    rels = {m["path"] for m in res["matches"]}
    assert not any(p.startswith("node_modules") for p in rels)
    assert not any(p.startswith(".hidden") for p in rels)


@pytest.mark.asyncio
async def test_grep_scope_via_path(fs: FsTools) -> None:
    grep = build_fs_grep(fs)
    res = await grep(query="needle", path="docs")
    rels = {m["path"] for m in res["matches"]}
    assert rels == {"docs/guide.md"}


@pytest.mark.asyncio
async def test_grep_extension_filter(fs: FsTools) -> None:
    grep = build_fs_grep(fs)
    res = await grep(query="needle", extensions=[".md"])
    assert all(m["path"].endswith(".md") for m in res["matches"])


@pytest.mark.asyncio
async def test_grep_case_insensitive(fs: FsTools, repo: Path) -> None:
    (repo / "src" / "shouty.py").write_text("# NEEDLE here\n")
    grep = build_fs_grep(fs)
    res = await grep(query="needle", case_insensitive=True)
    rels = {m["path"] for m in res["matches"]}
    assert "src/shouty.py" in rels


@pytest.mark.asyncio
async def test_grep_match_cap_truncates(fs: FsTools, repo: Path) -> None:
    (repo / "many.md").write_text("\n".join(f"needle {i}" for i in range(50)))
    fs.max_grep_matches = 5
    grep = build_fs_grep(fs)
    res = await grep(query="needle")
    assert res["truncated"] is True
    assert len(res["matches"]) == 5


@pytest.mark.asyncio
async def test_grep_empty_query_rejected(fs: FsTools) -> None:
    grep = build_fs_grep(fs)
    with pytest.raises(ValueError, match="non-empty"):
        await grep(query="")


@pytest.mark.asyncio
async def test_grep_bad_extension_rejected(fs: FsTools) -> None:
    grep = build_fs_grep(fs)
    with pytest.raises(ValueError, match="must start with"):
        await grep(query="x", extensions=["md"])


# ---- fs_write --------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_creates_file(fs_write_enabled: FsTools, repo: Path) -> None:
    write = build_fs_write(fs_write_enabled)
    res = await write(path="new.md", content="hello")
    assert res["created"] is True
    assert (repo / "new.md").read_text() == "hello"


@pytest.mark.asyncio
async def test_write_overwrites_existing(fs_write_enabled: FsTools, repo: Path) -> None:
    write = build_fs_write(fs_write_enabled)
    res = await write(path="README.md", content="new content")
    assert res["created"] is False
    assert (repo / "README.md").read_text() == "new content"


@pytest.mark.asyncio
async def test_write_creates_parent_dirs(fs_write_enabled: FsTools, repo: Path) -> None:
    write = build_fs_write(fs_write_enabled)
    res = await write(path="new_dir/deep/file.txt", content="x")
    assert res["created"] is True
    assert (repo / "new_dir" / "deep" / "file.txt").read_text() == "x"


@pytest.mark.asyncio
async def test_write_rejects_binary_suffix(fs_write_enabled: FsTools) -> None:
    write = build_fs_write(fs_write_enabled)
    with pytest.raises(ValueError, match="not a writable text file"):
        await write(path="evil.png", content="x")


@pytest.mark.asyncio
async def test_write_rejects_escape(fs_write_enabled: FsTools) -> None:
    write = build_fs_write(fs_write_enabled)
    with pytest.raises(ValueError, match="escapes fs root"):
        await write(path="../escape.txt", content="x")


@pytest.mark.asyncio
async def test_write_rejects_directory_path(fs_write_enabled: FsTools, repo: Path) -> None:
    (repo / "weird.md").mkdir()
    write = build_fs_write(fs_write_enabled)
    with pytest.raises(IsADirectoryError):
        await write(path="weird.md", content="x")
