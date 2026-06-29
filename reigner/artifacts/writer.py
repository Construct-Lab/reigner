"""ArtifactWriter — the only sanctioned way to write to library/artifacts/.

Atomic per-entity writes via a staging directory, schema-aware validation, and
a manifest at `extraction_meta.json`. Never exposed as an agent tool.

Atomicity protocol per `write_entity`:
  1. Stage to `<root>/.staging/<uuid>/` — fully written and validated there.
  2. If the destination already exists, rename it to `<root>/.trash/<uuid>/`.
  3. Atomically `rename` the staging directory into the destination.
  4. Drop the trash directory.
On failure during steps 1–3 the staging directory is removed and any moved
destination is restored, so the on-disk state is either the previous version
or the new one — never a half-written entity.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from reigner.artifacts.conventions import format_template
from reigner.artifacts.manifest import ExtractionMeta
from reigner.artifacts.schema import ArtifactSchema


class SchemaValidationError(ValueError):
    """Raised when sections or JSON artifacts violate the schema."""


class ArtifactWriteError(RuntimeError):
    """Raised on filesystem-level write failures."""


class ArtifactWriter:
    """Schema-aware, atomic writer for an entity's compiled artifacts.

    Bound to an artifact root and a schema; the only sanctioned way to write
    under ``library/artifacts/``. Write-side only — never exposed as a tool.
    """

    def __init__(self, root: str | Path, schema: ArtifactSchema) -> None:
        self.root = Path(root)
        self.schema = schema

    # ---- Public API --------------------------------------------------------

    def write_entity(
        self,
        *,
        sections: dict[str, str] | None = None,
        json_artifacts: dict[str, dict[str, Any]] | None = None,
        meta: dict[str, Any] | None = None,
        **identifiers: str,
    ) -> Path:
        """Atomically write all artifacts for one entity.

        Args:
            sections: section name -> prose content. Section names match
                `SectionSpec.name` from the schema; nested names like
                ``sections/business`` write to nested files.
            json_artifacts: JSON artifact filename -> payload dict.
            meta: extractor-owned manifest fields (``source_hash``,
                ``prompt_hash``, ``model``, …). Merged into
                ``extraction_meta.json`` under the ``extractor`` key.
            **identifiers: the entity_path placeholders (e.g. ``ticker=...``,
                ``fiscal_year=...``). Must exactly match the schema's
                ``entity_path`` keys.

        Returns:
            The absolute entity directory.
        """
        sections = sections or {}
        json_artifacts = json_artifacts or {}

        self._validate_identifiers(identifiers)
        self._validate_sections(sections)
        self._validate_json_artifacts(json_artifacts)

        dest = self.entity_dir(**identifiers)
        staging = self.root / ".staging" / uuid.uuid4().hex
        trash: Path | None = None

        try:
            staging.mkdir(parents=True, exist_ok=False)
            written_files = self._write_files(staging, sections, json_artifacts)
            self._write_manifest(staging, identifiers, written_files, meta)

            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                trash_root = self.root / ".trash"
                trash_root.mkdir(parents=True, exist_ok=True)
                trash = trash_root / uuid.uuid4().hex
                dest.rename(trash)
            staging.rename(dest)
        except Exception as exc:
            shutil.rmtree(staging, ignore_errors=True)
            if trash is not None and trash.exists() and not dest.exists():
                # Promotion failed after the previous version was moved aside;
                # restore it so we don't lose committed data.
                with contextlib.suppress(OSError):
                    trash.rename(dest)
            raise ArtifactWriteError(f"failed to write entity {identifiers}: {exc}") from exc

        if trash is not None:
            shutil.rmtree(trash, ignore_errors=True)

        return dest

    def entity_dir(self, **identifiers: str) -> Path:
        """Resolve the absolute entity directory under the writer's root."""
        rel = format_template(self.schema.entity_path, **identifiers)
        return self.root / rel

    # ---- Validation --------------------------------------------------------

    def _validate_identifiers(self, identifiers: dict[str, str]) -> None:
        expected = set(self.schema.entity_path_keys())
        given = set(identifiers)
        missing = expected - given
        if missing:
            raise SchemaValidationError(
                f"missing identifier(s) for entity_path={self.schema.entity_path!r}: "
                f"{sorted(missing)}"
            )
        extra = given - expected
        if extra:
            raise SchemaValidationError(
                f"unexpected identifier(s) for entity_path={self.schema.entity_path!r}: "
                f"{sorted(extra)}"
            )
        for key, value in identifiers.items():
            if not isinstance(value, str) or not value:
                raise SchemaValidationError(
                    f"identifier {key!r} must be a non-empty string, got {value!r}"
                )
            if "/" in value or "\\" in value:
                raise SchemaValidationError(
                    f"identifier {key!r}={value!r} cannot contain path separators"
                )

    def _validate_sections(self, sections: dict[str, str]) -> None:
        for required in self.schema.required_sections():
            if required.name not in sections:
                raise SchemaValidationError(f"missing required section {required.name!r}")
        for name, content in sections.items():
            if not isinstance(content, str):
                raise SchemaValidationError(
                    f"section {name!r} content must be str, got {type(content).__name__}"
                )
            matched = self.schema.section(name)
            if matched is None:
                continue
            if matched.max_chars is not None and len(content) > matched.max_chars:
                raise SchemaValidationError(
                    f"section {name!r} length {len(content)} exceeds max_chars={matched.max_chars}"
                )

    def _validate_json_artifacts(self, json_artifacts: dict[str, dict[str, Any]]) -> None:
        for spec in self.schema.json_artifacts:
            if spec.name not in json_artifacts:
                if spec.required_field_names:
                    raise SchemaValidationError(f"missing required JSON artifact {spec.name!r}")
                continue
            payload = json_artifacts[spec.name]
            if not isinstance(payload, dict):
                raise SchemaValidationError(
                    f"json_artifact {spec.name!r} must be a dict, got {type(payload).__name__}"
                )
            missing = spec.required_field_names - set(payload)
            if missing:
                raise SchemaValidationError(
                    f"json_artifact {spec.name!r} missing required fields: {sorted(missing)}"
                )
            for field_name, expected_type in spec.fields.items():
                if field_name not in payload:
                    continue
                value = payload[field_name]
                if value is None:
                    continue
                if not isinstance(value, expected_type):
                    raise SchemaValidationError(
                        f"json_artifact {spec.name!r} field {field_name!r}: expected "
                        f"{expected_type.__name__}, got {type(value).__name__}"
                    )

    # ---- Writing -----------------------------------------------------------

    def _write_files(
        self,
        staging: Path,
        sections: dict[str, str],
        json_artifacts: dict[str, dict[str, Any]],
    ) -> list[str]:
        written: list[str] = []
        for name, content in sections.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            written.append(name)
        for name, payload in json_artifacts.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, indent=2, sort_keys=True))
            written.append(name)
        return sorted(written)

    def _write_manifest(
        self,
        staging: Path,
        identifiers: dict[str, str],
        files: list[str],
        meta: dict[str, Any] | None,
    ) -> None:
        manifest = ExtractionMeta(
            schema_version=self.schema.version,
            identifiers=dict(identifiers),
            files=files,
            extractor=meta,
        )
        (staging / self.schema.extraction_meta).write_text(manifest.to_json())
