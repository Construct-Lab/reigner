"""`SearchIndex` Protocol — the minimal contract every retrieval backend implements."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

from reigner.tools.base import RunnableToolAdapter

ToolCallable = Callable[..., Awaitable[dict[str, Any]]]
"""An async tool function decorated with `@tool` from `reigner.tools.base`.

Kept as a public alias for backend authors who want to type the raw closures
before adapting them. The Protocol's ``tools()`` returns adapted instances.
"""


@runtime_checkable
class SearchIndex(Protocol):
    """Pluggable retrieval backend.

    Implementers MUST declare ``__reigner_backend__ = "search"`` as a class
    attribute. The marker is the *role label* that distinguishes a retrieval
    backend from any other class that happens to expose a ``tools()`` method
    (e.g. ``ArtifactStore``, ``FsTools``). Without it, those classes would
    satisfy this Protocol structurally — duck typing alone is too loose for
    a substitution point users wire by hand.

    Backends own their own tool names: this class exposes
    ``bm25_search``/``filtered_search``/``section_search``; a future vector
    backend might expose ``vector_search(query, namespace, top_k)`` instead.
    The harness consumes whatever tools are returned without caring which
    backend produced them.
    """

    __reigner_backend__: ClassVar[Literal["search"]]

    def tools(self) -> list[RunnableToolAdapter]:
        """Return the loop-ready tool adapters this backend contributes."""
        ...


__all__ = ["SearchIndex", "ToolCallable"]
