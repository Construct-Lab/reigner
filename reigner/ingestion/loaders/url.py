"""URL loader.

Fetches ``http(s)://`` sources via ``httpx``. The ``httpx`` import is
deferred so file-only ingestion (PDF / markdown / JSON) doesn't require
the optional ``ingestion`` extra to be installed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from reigner.ingestion.loaders.base import LoadedDocument


class UrlLoader:
    """Fetches an http(s) URL.

    Pass ``transport`` to inject a custom ``httpx`` transport (used by
    tests via ``httpx.MockTransport``). ``meta_extractor`` runs on the
    URL string and its returned dict is merged into ``meta``.
    """

    schemes: ClassVar[frozenset[str]] = frozenset({"http", "https"})

    def __init__(
        self,
        meta_extractor: Callable[[str], dict[str, Any]] | None = None,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
        transport: Any | None = None,
    ) -> None:
        self._meta_extractor = meta_extractor
        self._timeout = timeout
        self._headers = headers or {}
        self._transport = transport

    async def load(self, source: str | Path) -> LoadedDocument:
        """Fetch an http(s) URL into bytes plus response metadata.

        Args:
            source: The URL to fetch.

        Returns:
            The response body and metadata (status, content-type, fetch time).

        Raises:
            ImportError: If the optional ``httpx`` dependency is not installed.
        """
        try:
            import httpx
        except ImportError as exc:
            raise ImportError(
                "UrlLoader requires httpx. Install with `pip install reigner[ingestion]`."
            ) from exc
        url = str(source)
        client_kwargs: dict[str, Any] = {
            "timeout": self._timeout,
            "headers": self._headers,
        }
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        async with httpx.AsyncClient(**client_kwargs) as client:
            response = await client.get(url)
            response.raise_for_status()
        meta: dict[str, Any] = {
            "source": url,
            "url": url,
            "size_bytes": len(response.content),
            "content_type": response.headers.get("content-type", ""),
            "status_code": response.status_code,
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        if self._meta_extractor is not None:
            meta.update(self._meta_extractor(url))
        return LoadedDocument(raw=response.content, meta=meta)
