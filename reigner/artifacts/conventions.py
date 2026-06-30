"""Path-template helpers and default layout constants.

Pure string operations — no filesystem I/O, no schema dependency. Used by
ArtifactSchema to resolve placeholders and by ArtifactWriter to compose paths.
"""

from __future__ import annotations

import re
from typing import Final

DEFAULT_ENTITY_PATH: Final = "{entity_id}/{version}"
DEFAULT_RAW_PATH: Final = "raw/{entity_id}/{version}.{ext}"
DEFAULT_EXTRACTION_META: Final = "extraction_meta.json"
DEFAULT_TEXT_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {".csv", ".json", ".jsonl", ".md", ".txt", ".tsv", ".yaml", ".yml"}
)

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def parse_template_keys(template: str) -> tuple[str, ...]:
    """Extract `{name}` placeholders from a template, in first-occurrence order."""
    seen: list[str] = []
    for m in _PLACEHOLDER_RE.finditer(template):
        name = m.group(1)
        if name not in seen:
            seen.append(name)
    return tuple(seen)


def format_template(template: str, **values: str) -> str:
    """Fill a template's placeholders. Raise on missing or extra keys."""
    keys = set(parse_template_keys(template))
    given = set(values)
    missing = keys - given
    if missing:
        raise ValueError(f"template {template!r} missing placeholders: {sorted(missing)}")
    extra = given - keys
    if extra:
        raise ValueError(f"template {template!r} got unexpected keys: {sorted(extra)}")
    return template.format(**values)
