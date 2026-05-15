from __future__ import annotations

from reigner.ingestion.loaders import (
    JsonLoader,
    LoadedDocument,
    Loader,
    MdLoader,
    PdfLoader,
    UrlLoader,
)


def test_loaded_document_meta_defaults_empty() -> None:
    doc = LoadedDocument(raw=b"x")
    assert doc.raw == b"x"
    assert doc.meta == {}


def test_concrete_loaders_satisfy_protocol() -> None:
    assert isinstance(PdfLoader(), Loader)
    assert isinstance(MdLoader(), Loader)
    assert isinstance(JsonLoader(), Loader)
    assert isinstance(UrlLoader(), Loader)


def test_file_loaders_expose_extensions() -> None:
    assert PdfLoader.extensions == frozenset({".pdf"})
    assert MdLoader.extensions == frozenset({".md", ".markdown"})
    assert JsonLoader.extensions == frozenset({".json", ".jsonl"})


def test_url_loader_exposes_schemes() -> None:
    assert UrlLoader.schemes == frozenset({"http", "https"})
