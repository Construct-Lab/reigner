"""ArtifactStore — read-side handle bound to an artifact root and schema.

The store is the trust boundary for the agent's read tools: every path the
agent supplies passes through :meth:`ArtifactStore.resolve`, which rejects
absolute paths and anything that escapes the root via ``..`` traversal.

The store does not import schema fields at runtime to gate which paths exist
on disk — operator-added files and ``extraction_meta.json`` must remain
readable. The schema is consulted only for text-suffix classification (read
tool) and for synthesizing argument signatures (the ``list_*`` factories).

See SPEC §6.4 (built-in artifact tools) and §7 (artifact system).
"""

from __future__ import annotations

from pathlib import Path

from reigner.artifacts.schema import ArtifactSchema
from reigner.tools.base import RunnableToolAdapter, to_runnable


class ArtifactStore:
    """Schema-aware view of a compiled artifact root for read-side tools."""

    def __init__(self, root: str | Path, schema: ArtifactSchema) -> None:
        self.root = Path(root).resolve()
        self.schema = schema

    # ---- Trust boundary ----------------------------------------------------

    def resolve(self, rel: str) -> Path:
        """Resolve a root-relative path, rejecting traversal escapes.

        ``rel`` must be a non-empty relative POSIX-style path. The resolved
        path is rejected if it doesn't stay under ``self.root``.
        """
        if not isinstance(rel, str) or not rel:
            raise ValueError("path must be a non-empty string")
        if rel.startswith(("/", "\\")):
            raise ValueError(f"path must be relative, got {rel!r}")
        candidate = (self.root / rel).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"path {rel!r} escapes artifact root") from exc
        return candidate

    def resolve_entity(self, **identifiers: str) -> Path:
        """Resolve an entity directory from its ``entity_path`` identifiers."""
        keys = self.schema.entity_path_keys()
        missing = [k for k in keys if k not in identifiers]
        if missing:
            raise ValueError(f"missing identifier(s): {missing}")
        extra = [k for k in identifiers if k not in keys]
        if extra:
            raise ValueError(f"unexpected identifier(s): {extra}")
        for k, v in identifiers.items():
            if not isinstance(v, str) or not v:
                raise ValueError(f"identifier {k!r} must be a non-empty string")
            if "/" in v or "\\" in v:
                raise ValueError(f"identifier {k!r}={v!r} cannot contain path separators")
        rel = "/".join(identifiers[k] for k in keys)
        return self.resolve(rel)

    # ---- Tool assembly -----------------------------------------------------

    def tools(self) -> list[RunnableToolAdapter]:
        """Build the six SPEC §6.4 artifact tools as RunnableTool wrappers."""
        from reigner.tools.artifacts.grep import build_grep_artifact
        from reigner.tools.artifacts.json_field import build_get_json_field
        from reigner.tools.artifacts.list import (
            build_get_section,
            build_list_documents,
            build_list_versions,
        )
        from reigner.tools.artifacts.read import build_read_artifact_file

        funcs = [
            build_read_artifact_file(self),
            build_grep_artifact(self),
            build_get_json_field(self),
            build_list_documents(self),
            build_list_versions(self),
            build_get_section(self),
        ]
        return [to_runnable(f) for f in funcs]


__all__ = ["ArtifactStore"]
