"""Multi-root FsTools — the virtual unified tree across several repos.

Lays down two repo-shaped trees (``backend`` and ``frontend``) under one
FsTools and exercises the virtual-tree resolve boundary, root-prefixed
output, and cross-root fan-out for grep/glob.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from reigner.tools.fs import FsTools
from reigner.tools.fs.glob import build_fs_glob
from reigner.tools.fs.grep import build_fs_grep
from reigner.tools.fs.ls import build_fs_ls
from reigner.tools.fs.read import build_fs_read
from reigner.tools.fs.write import build_fs_write


@pytest.fixture
def backend(tmp_path: Path) -> Path:
    root = tmp_path / "api"
    (root / "app").mkdir(parents=True)
    (root / "app" / "auth.py").write_text("def login():  # needle\n    return 1\n")
    (root / "README.md").write_text("backend needle\n")
    return root


@pytest.fixture
def frontend(tmp_path: Path) -> Path:
    root = tmp_path / "web"
    (root / "src").mkdir(parents=True)
    (root / "src" / "auth.ts").write_text("export const login = () => {} // needle\n")
    (root / "README.md").write_text("frontend needle\n")
    return root


@pytest.fixture
def fs(backend: Path, frontend: Path) -> FsTools:
    return FsTools(roots={"backend": backend, "frontend": frontend})


# ---- construction ----------------------------------------------------------


def test_requires_exactly_one_of_root_or_roots(backend: Path) -> None:
    with pytest.raises(ValueError, match="exactly one of 'root' or 'roots'"):
        FsTools()
    with pytest.raises(ValueError, match="exactly one of 'root' or 'roots'"):
        FsTools(backend, roots={"backend": backend})


def test_rejects_empty_roots_map() -> None:
    with pytest.raises(ValueError, match="non-empty map"):
        FsTools(roots={})


def test_single_root_root_property_still_works(backend: Path) -> None:
    single = FsTools(backend)
    assert single.multi_root is False
    assert single.root == backend.resolve()


def test_multi_root_root_property_raises(fs: FsTools) -> None:
    assert fs.multi_root is True
    with pytest.raises(AttributeError, match="multi-root mode"):
        _ = fs.root


# ---- resolve (trust boundary) ----------------------------------------------


def test_resolve_maps_first_segment_to_root(fs: FsTools, backend: Path) -> None:
    root_name, resolved = fs.resolve("backend/app/auth.py")
    assert root_name == "backend"
    assert resolved == backend.resolve() / "app" / "auth.py"


def test_resolve_bare_root_name(fs: FsTools, frontend: Path) -> None:
    root_name, resolved = fs.resolve("frontend")
    assert root_name == "frontend"
    assert resolved == frontend.resolve()


def test_resolve_unknown_root_raises(fs: FsTools) -> None:
    with pytest.raises(ValueError, match="unknown root 'nope'; roots are: backend, frontend"):
        fs.resolve("nope/file.py")


def test_resolve_rejects_cross_root_traversal(fs: FsTools) -> None:
    # Climbing out of backend into frontend must be rejected against the
    # *selected* root, not merely the virtual tree.
    with pytest.raises(ValueError, match="escapes root 'backend'"):
        fs.resolve("backend/../frontend/README.md")


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks require admin on Windows")
def test_resolve_rejects_symlink_escaping_its_root(
    fs: FsTools, backend: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("nope")
    os.symlink(outside, backend / "escape.md")
    with pytest.raises(ValueError, match="escapes root 'backend'"):
        fs.resolve("backend/escape.md")


# ---- display ---------------------------------------------------------------


def test_display_is_root_prefixed(fs: FsTools, backend: Path) -> None:
    assert fs.display("backend", backend.resolve() / "app" / "auth.py") == "backend/app/auth.py"
    assert fs.display("backend", backend.resolve()) == "backend"


# ---- fs_ls -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_ls_top_lists_root_names(fs: FsTools) -> None:
    ls = build_fs_ls(fs)
    for top in ("", "."):
        res = await ls(path=top)
        names = {e["name"] for e in res["entries"]}
        assert names == {"backend", "frontend"}
        assert all(e["type"] == "dir" for e in res["entries"])


@pytest.mark.asyncio
async def test_ls_into_a_root(fs: FsTools) -> None:
    ls = build_fs_ls(fs)
    res = await ls(path="backend")
    names = {e["name"] for e in res["entries"]}
    assert "app" in names
    assert "README.md" in names


# ---- fs_read ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_root_prefixed_path(fs: FsTools) -> None:
    read = build_fs_read(fs)
    res = await read(path="frontend/src/auth.ts")
    assert "export const login" in res["content"]


@pytest.mark.asyncio
async def test_read_unknown_root_raises(fs: FsTools) -> None:
    read = build_fs_read(fs)
    with pytest.raises(ValueError, match="unknown root"):
        await read(path="mobile/src/auth.ts")


# ---- fs_grep ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_grep_fans_out_across_roots(fs: FsTools) -> None:
    grep = build_fs_grep(fs)
    res = await grep(query="needle")
    rels = {m["path"] for m in res["matches"]}
    assert "backend/app/auth.py" in rels
    assert "backend/README.md" in rels
    assert "frontend/src/auth.ts" in rels
    assert "frontend/README.md" in rels


@pytest.mark.asyncio
async def test_grep_scoped_to_one_root(fs: FsTools) -> None:
    grep = build_fs_grep(fs)
    res = await grep(query="needle", path="frontend")
    rels = {m["path"] for m in res["matches"]}
    assert rels and all(p.startswith("frontend/") for p in rels)


@pytest.mark.asyncio
async def test_grep_cap_is_global_across_roots(fs: FsTools) -> None:
    fs.max_grep_matches = 2
    grep = build_fs_grep(fs)
    res = await grep(query="needle")
    assert res["truncated"] is True
    assert len(res["matches"]) == 2


# ---- fs_glob ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_glob_fans_out_across_roots(fs: FsTools) -> None:
    glob = build_fs_glob(fs)
    res = await glob(pattern="**/README.md")
    assert "backend/README.md" in res["paths"]
    assert "frontend/README.md" in res["paths"]


@pytest.mark.asyncio
async def test_glob_scoped_to_one_root(fs: FsTools) -> None:
    glob = build_fs_glob(fs)
    res = await glob(pattern="**/*.py", base="backend")
    assert res["paths"] == ["backend/app/auth.py"]


# ---- fs_write --------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_resolves_and_reports_root_prefixed_path(backend: Path, frontend: Path) -> None:
    fs = FsTools(roots={"backend": backend, "frontend": frontend}, write_enabled=True)
    write = build_fs_write(fs)
    res = await write(path="frontend/notes.md", content="hi")
    assert res["created"] is True
    assert res["path"] == "frontend/notes.md"
    assert (frontend / "notes.md").read_text() == "hi"
