"""Schema-derived listing tools: list_documents, list_versions, get_section.

SPEC §6.4 hardcodes ``list_versions(entity_id)`` and
``get_section(entity_id, version, section)`` — those signatures assume the
default two-level ``{entity_id}/{version}`` ``entity_path``. We generalise
to N-level identifier paths by synthesizing each tool's ``inspect.Signature``
from ``schema.entity_path_keys()`` at build time, so the JSON Schema the
model sees matches the project's actual entity shape.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from reigner.tools.base import tool

if TYPE_CHECKING:
    from reigner.tools.artifacts.store import ArtifactStore


# ---------------------------------------------------------------------------
# list_documents
# ---------------------------------------------------------------------------


def build_list_documents(
    store: ArtifactStore,
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build a @tool closure: list all entities, optionally filtered by identifier keys.

    Filters are keyword arguments keyed on ``entity_path`` placeholders. An
    omitted key matches everything at that level. Returns each entity as the
    mapping of its identifier values (which together form its relative path).
    """
    keys = store.schema.entity_path_keys()

    params = [
        inspect.Parameter(
            k,
            inspect.Parameter.KEYWORD_ONLY,
            default=None,
            annotation=str | None,
        )
        for k in keys
    ]
    sig = inspect.Signature(parameters=params, return_annotation=dict[str, Any])

    async def list_documents(**filters: str | None) -> dict[str, Any]:
        for k, v in filters.items():
            if v is not None and (not isinstance(v, str) or not v):
                raise ValueError(f"filter {k!r} must be a non-empty string or None")
        entities = _walk_entities(store.root, len(keys))
        results: list[dict[str, str]] = []
        for ent in entities:
            ids = dict(zip(keys, ent.parts[-len(keys) :], strict=True))
            if all(filters.get(k) in (None, ids[k]) for k in keys):
                results.append(ids)
        results.sort(key=lambda d: tuple(d[k] for k in keys))
        return {"entities": results, "count": len(results), "filters": _clean(filters)}

    list_documents.__signature__ = sig  # type: ignore[attr-defined]
    filter_doc = ", ".join(f"{k}: str | None = None" for k in keys) if keys else "no filters"
    list_documents.__doc__ = (
        "List entity identifiers in the artifact store, optionally filtered.\n\n"
        f"Filters (all optional): {filter_doc}.\n"
        "Returns {entities, count, filters}; each entity is a mapping of its "
        "identifier keys to values."
    )
    return tool(readonly=True)(list_documents)


# ---------------------------------------------------------------------------
# list_versions
# ---------------------------------------------------------------------------


def build_list_versions(
    store: ArtifactStore,
) -> Callable[..., Awaitable[list[str]]]:
    """Build a @tool closure: list values of the trailing entity_path placeholder.

    Given an ``entity_path`` like ``{ticker}/{fiscal_year}``, the tool's
    signature requires ``ticker`` and returns the available ``fiscal_year``
    values. For a single-key entity_path, takes no arguments and lists the
    top-level identifiers.
    """
    keys = store.schema.entity_path_keys()
    *prefix_keys, trailing = keys

    params = [
        inspect.Parameter(k, inspect.Parameter.KEYWORD_ONLY, annotation=str) for k in prefix_keys
    ]
    sig = inspect.Signature(parameters=params, return_annotation=list[str])

    async def list_versions(**identifiers: str) -> list[str]:
        for k in prefix_keys:
            v = identifiers.get(k)
            if not isinstance(v, str) or not v:
                raise ValueError(f"identifier {k!r} must be a non-empty string")
            if "/" in v or "\\" in v:
                raise ValueError(f"identifier {k!r}={v!r} cannot contain path separators")
        if prefix_keys:
            prefix_dir = store.resolve("/".join(identifiers[k] for k in prefix_keys))
        else:
            prefix_dir = store.root
        if not prefix_dir.is_dir():
            return []
        return sorted(p.name for p in prefix_dir.iterdir() if p.is_dir())

    list_versions.__signature__ = sig  # type: ignore[attr-defined]
    prefix_doc = ", ".join(prefix_keys) if prefix_keys else "no arguments"
    list_versions.__doc__ = (
        f"List available {trailing!r} values for the given prefix ({prefix_doc}).\n\n"
        "Returns a sorted list of directory names at the trailing level of "
        "the entity_path."
    )
    return tool(readonly=True)(list_versions)


# ---------------------------------------------------------------------------
# get_section
# ---------------------------------------------------------------------------


def build_get_section(
    store: ArtifactStore,
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build a @tool closure: read a named section file under one entity.

    Signature: ``section: str`` plus one ``str`` parameter per entity_path key.
    Convenience over ``read_artifact_file`` for the common section-name lookup
    pattern (SPEC §6.4).
    """
    keys = store.schema.entity_path_keys()

    params = [inspect.Parameter("section", inspect.Parameter.KEYWORD_ONLY, annotation=str)]
    params.extend(
        inspect.Parameter(k, inspect.Parameter.KEYWORD_ONLY, annotation=str) for k in keys
    )
    sig = inspect.Signature(parameters=params, return_annotation=dict[str, Any])

    async def get_section(section: str, **identifiers: str) -> dict[str, Any]:
        if not isinstance(section, str) or not section:
            raise ValueError("section must be a non-empty string")
        if section.startswith("/") or ".." in section.split("/"):
            raise ValueError(f"section {section!r} must be a relative name with no traversal")
        entity_dir = store.resolve_entity(**identifiers)
        if not entity_dir.is_dir():
            raise FileNotFoundError(f"no entity at {entity_dir.relative_to(store.root)}")
        target = (entity_dir / section).resolve()
        try:
            target.relative_to(store.root)
        except ValueError as exc:
            raise ValueError(f"section {section!r} escapes artifact root") from exc
        if not target.is_file():
            raise FileNotFoundError(f"section {section!r} not found under entity")
        content = target.read_text()
        rel = str(target.relative_to(store.root))
        return {"section": section, "path": rel, "content": content, "size": len(content)}

    get_section.__signature__ = sig  # type: ignore[attr-defined]
    id_doc = ", ".join(keys) if keys else "no identifiers"
    get_section.__doc__ = (
        f"Read the section file ``section`` under the entity at ({id_doc}).\n\n"
        "Returns {section, path, content, size}. For binary or paginated reads, "
        "use ``read_artifact_file`` instead."
    )
    return tool(readonly=True)(get_section)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _walk_entities(root: Any, depth: int) -> list[Any]:
    """Directories at exactly ``depth`` levels below ``root``."""
    out: list[Any] = []

    def _recurse(p: Any, remaining: int) -> None:
        if remaining == 0:
            out.append(p)
            return
        if not p.is_dir():
            return
        for child in sorted(p.iterdir()):
            if child.name.startswith(".") or not child.is_dir():
                continue
            _recurse(child, remaining - 1)

    if not root.exists():
        return out
    _recurse(root, depth)
    return out


def _clean(filters: dict[str, Any]) -> dict[str, str]:
    return {k: v for k, v in filters.items() if v is not None}


__all__ = [
    "build_get_section",
    "build_list_documents",
    "build_list_versions",
]
