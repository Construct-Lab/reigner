from __future__ import annotations

import pytest

from reigner.ingestion.loaders import UrlLoader

httpx = pytest.importorskip("httpx")


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        content=b"hello world",
        headers={"content-type": "text/plain; charset=utf-8"},
    )


def _500_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, content=b"boom")


async def test_load_returns_response_bytes_and_meta() -> None:
    transport = httpx.MockTransport(_ok_handler)
    doc = await UrlLoader(transport=transport).load("https://example.test/x")
    assert doc.raw == b"hello world"
    assert doc.meta["url"] == "https://example.test/x"
    assert doc.meta["source"] == "https://example.test/x"
    assert doc.meta["status_code"] == 200
    assert doc.meta["size_bytes"] == len(b"hello world")
    assert doc.meta["content_type"] == "text/plain; charset=utf-8"
    assert "fetched_at" in doc.meta


async def test_meta_extractor_runs_on_url() -> None:
    transport = httpx.MockTransport(_ok_handler)
    doc = await UrlLoader(
        transport=transport,
        meta_extractor=lambda url: {"host": url.split("/")[2]},
    ).load("https://example.test/x")
    assert doc.meta["host"] == "example.test"


async def test_http_error_raises() -> None:
    transport = httpx.MockTransport(_500_handler)
    with pytest.raises(httpx.HTTPStatusError):
        await UrlLoader(transport=transport).load("https://example.test/x")
