from __future__ import annotations

from pathlib import Path

import pytest

from reigner.ingestion.loaders import MdLoader


async def test_plain_markdown_no_frontmatter_key(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_bytes(b"# Hello\n\nbody\n")
    doc = await MdLoader().load(path)
    assert doc.raw == b"# Hello\n\nbody\n"
    assert "frontmatter" not in doc.meta
    assert doc.meta["content_type"] == "text/markdown"


async def test_yaml_frontmatter_parsed(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_bytes(b"---\ntitle: Q4 Update\ntags:\n  - finance\n  - draft\n---\n# Body\n")
    doc = await MdLoader().load(path)
    assert doc.meta["frontmatter"] == {
        "title": "Q4 Update",
        "tags": ["finance", "draft"],
    }
    # raw still includes the front-matter block
    assert doc.raw.startswith(b"---\n")


async def test_unterminated_frontmatter_ignored(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_bytes(b"---\ntitle: oops\n# never closed\n")
    doc = await MdLoader().load(path)
    assert "frontmatter" not in doc.meta


async def test_malformed_yaml_frontmatter_ignored(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_bytes(b"---\n: : not: yaml:\n---\nbody\n")
    doc = await MdLoader().load(path)
    assert "frontmatter" not in doc.meta


async def test_non_mapping_frontmatter_ignored(tmp_path: Path) -> None:
    # YAML parses to a list, not a dict — should be ignored.
    path = tmp_path / "note.md"
    path.write_bytes(b"---\n- one\n- two\n---\nbody\n")
    doc = await MdLoader().load(path)
    assert "frontmatter" not in doc.meta


async def test_markdown_extension_alias(tmp_path: Path) -> None:
    path = tmp_path / "note.markdown"
    path.write_bytes(b"# x\n")
    doc = await MdLoader().load(path)
    assert doc.meta["filename"] == "note.markdown"


async def test_meta_extractor_merged(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_bytes(b"# x\n")
    doc = await MdLoader(meta_extractor=lambda p: {"slug": p.stem}).load(path)
    assert doc.meta["slug"] == "note"


async def test_non_utf8_frontmatter_ignored(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_bytes(b"---\ntitle: \xff\xfe\n---\nbody\n")
    doc = await MdLoader().load(path)
    assert "frontmatter" not in doc.meta


@pytest.mark.parametrize("payload", [b"", b"\n", b"---\n"])
async def test_edge_cases_dont_raise(tmp_path: Path, payload: bytes) -> None:
    path = tmp_path / "note.md"
    path.write_bytes(payload)
    doc = await MdLoader().load(path)
    assert doc.raw == payload
