"""ExtractionMeta — the per-entity manifest written alongside artifacts.

Splits writer-owned envelope fields (`schema_version`, `written_at`,
`identifiers`, `files`) from extractor-owned payload (`source_hash`,
`prompt_hash`, `model`, `cost_usd`, …). Both halves are merged into a single
`extraction_meta.json`. See SPEC.md §7.3 and issue #13.
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
    schema_version: str
    identifiers: dict[str, str]
    files: list[str]
    extractor: dict[str, Any] | None = None
    written_at: str = field(default_factory=_utc_now_iso)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> ExtractionMeta:
        data = json.loads(s)
        return cls(
            schema_version=data["schema_version"],
            identifiers=dict(data["identifiers"]),
            files=list(data["files"]),
            extractor=data.get("extractor"),
            written_at=data.get("written_at", _utc_now_iso()),
        )
