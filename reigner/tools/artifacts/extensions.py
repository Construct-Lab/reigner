"""Suffix classification — keep schema.text_extensions checks in one place."""

from __future__ import annotations

from pathlib import Path

from reigner.artifacts.schema import ArtifactSchema


def is_text_file(path: Path, schema: ArtifactSchema) -> bool:
    """True when ``path`` is readable as text.

    Suffixless files are treated as text — section files in document_qa-style
    schemas (e.g. ``document_summary``, ``sections/business``) deliberately
    omit an extension, but they are prose by contract. Files with a suffix
    must match the schema's ``text_extensions`` allowlist; everything else
    (``.pdf``, ``.bin``, …) is rejected.
    """
    suffix = path.suffix.lower()
    if not suffix:
        return True
    return suffix in schema.text_extensions
