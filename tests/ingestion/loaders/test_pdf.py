from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from reigner.ingestion.loaders import PdfLoader

# A valid empty PDF — minimal header + EOF marker. Just bytes, never parsed.
_PDF_BYTES = b"%PDF-1.4\n%%EOF\n"


@pytest.fixture
def pdf_file(tmp_path: Path) -> Path:
    path = tmp_path / "AAPL_10K_2024.pdf"
    path.write_bytes(_PDF_BYTES)
    return path


async def test_load_returns_raw_bytes_and_default_meta(pdf_file: Path) -> None:
    doc = await PdfLoader().load(pdf_file)
    assert doc.raw == _PDF_BYTES
    assert doc.meta == {
        "source": str(pdf_file),
        "filename": "AAPL_10K_2024.pdf",
        "size_bytes": len(_PDF_BYTES),
        "content_type": "application/pdf",
    }


async def test_load_accepts_str_path(pdf_file: Path) -> None:
    doc = await PdfLoader().load(str(pdf_file))
    assert doc.meta["filename"] == "AAPL_10K_2024.pdf"


async def test_meta_extractor_dict_is_merged(pdf_file: Path) -> None:
    def parse(path: Path) -> dict[str, Any]:
        ticker, _, year = path.stem.split("_")
        return {"ticker": ticker, "fiscal_year": int(year)}

    doc = await PdfLoader(meta_extractor=parse).load(pdf_file)
    assert doc.meta["ticker"] == "AAPL"
    assert doc.meta["fiscal_year"] == 2024
    # loader-provided keys still present
    assert doc.meta["content_type"] == "application/pdf"


async def test_meta_extractor_overrides_defaults(pdf_file: Path) -> None:
    doc = await PdfLoader(meta_extractor=lambda _: {"content_type": "application/pdf+custom"}).load(
        pdf_file
    )
    assert doc.meta["content_type"] == "application/pdf+custom"
