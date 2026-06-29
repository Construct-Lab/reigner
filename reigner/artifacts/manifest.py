"""ExtractionMeta — the per-entity manifest written alongside artifacts.

Splits writer-owned envelope fields (`schema_version`, `written_at`,
`identifiers`, `files`) from extractor-owned payload (`source_hash`,
`prompt_hash`, `model`, `cost_usd`, …). Both halves are merged into a single
`extraction_meta.json`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class ExtractionMeta:
    """Per-entity manifest written alongside an entity's artifacts.

    Attributes:
        schema_version: Version of the artifact schema used for extraction.
        identifiers: Identity fields locating the entity (e.g. ``entity_id``).
        files: Artifact file paths written for this entity, relative to root.
        extractor: Optional extractor-owned payload (hashes, model, cost).
        written_at: ISO-8601 UTC timestamp of when the manifest was written.
    """

    schema_version: str
    identifiers: dict[str, str]
    files: list[str]
    extractor: dict[str, Any] | None = None
    written_at: str = field(default_factory=_utc_now_iso)

    def to_json(self) -> str:
        """Serialize the manifest to indented, key-sorted JSON."""
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> ExtractionMeta:
        """Reconstruct an :class:`ExtractionMeta` from its JSON form.

        Args:
            s: JSON text previously produced by :meth:`to_json`.

        Returns:
            The decoded manifest, defaulting ``written_at`` if absent.
        """
        data = json.loads(s)
        return cls(
            schema_version=data["schema_version"],
            identifiers=dict(data["identifiers"]),
            files=list(data["files"]),
            extractor=data.get("extractor"),
            written_at=data.get("written_at", _utc_now_iso()),
        )
