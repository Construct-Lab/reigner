from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from reigner.ingestion.loaders import HtmlLoader

_HTML_BYTES = b"<!doctype html><title>Filing</title><body>Hello</body>"


@pytest.fixture
def html_file(tmp_path: Path) -> Path:
    path = tmp_path / "AAPL_10K_2024.html"
    path.write_bytes(_HTML_BYTES)
    return path


async def test_load_returns_raw_bytes_and_default_meta(html_file: Path) -> None:
    doc = await HtmlLoader().load(html_file)
    assert doc.raw == _HTML_BYTES
    assert doc.meta == {
        "source": str(html_file),
        "filename": "AAPL_10K_2024.html",
        "size_bytes": len(_HTML_BYTES),
        "content_type": "text/html",
    }


async def test_load_accepts_str_path(html_file: Path) -> None:
    doc = await HtmlLoader().load(str(html_file))
    assert doc.meta["filename"] == "AAPL_10K_2024.html"


async def test_htm_extension_is_owned() -> None:
    assert HtmlLoader.extensions == frozenset({".html", ".htm"})


async def test_meta_extractor_dict_is_merged(html_file: Path) -> None:
    def parse(path: Path) -> dict[str, Any]:
        ticker, _, year = path.stem.split("_")
        return {"ticker": ticker, "fiscal_year": int(year)}

    doc = await HtmlLoader(meta_extractor=parse).load(html_file)
    assert doc.meta["ticker"] == "AAPL"
    assert doc.meta["fiscal_year"] == 2024
    # loader-provided keys still present
    assert doc.meta["content_type"] == "text/html"


async def test_meta_extractor_overrides_defaults(html_file: Path) -> None:
    doc = await HtmlLoader(meta_extractor=lambda _: {"content_type": "application/xhtml+xml"}).load(
        html_file
    )
    assert doc.meta["content_type"] == "application/xhtml+xml"
