"""ArtifactSchema and field-spec types — the on-disk contract.

See SPEC.md §7.1 (declarative shape), §8.1 (field-level types for validation),
and issue #13.

The schema is the contract shared by the write side (T-13: ArtifactWriter, plus
LLMExtractor in T-14) and the read side (T-09: ArtifactStore tools). The write
side uses the validation surface (`required`, `max_chars`, `fields`); the read
side touches only `.name`-level metadata. See TASKS.md coordination note for #9.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from reigner.artifacts.conventions import (
    DEFAULT_ENTITY_PATH,
    DEFAULT_EXTRACTION_META,
    DEFAULT_RAW_PATH,
    DEFAULT_TEXT_EXTENSIONS,
    parse_template_keys,
)


@dataclass
class SectionSpec:
    """A prose-section artifact under the entity directory.

    Section names containing `*` are globs: they declare an allowed prefix
    (e.g. `sections/*`) but cannot be `required`, since there is no fixed
    name to enforce.
    """

    name: str
    required: bool = False
    max_chars: int | None = None

    @property
    def is_glob(self) -> bool:
        return "*" in self.name

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("SectionSpec.name must be non-empty")
        if self.is_glob and self.required:
            raise ValueError(
                f"glob section {self.name!r} cannot be required (no fixed name to enforce)"
            )
        if self.max_chars is not None and self.max_chars <= 0:
            raise ValueError(f"SectionSpec.max_chars must be positive, got {self.max_chars}")


@dataclass
class JsonArtifactSpec:
    """A JSON artifact under the entity directory.

    `fields` declares expected top-level keys and their Python types. By
    default every declared field is required; pass `required_fields` to
    relax this. An empty `fields` dict means "no field-level validation"
    and the artifact is treated as optional.
    """

    name: str
    fields: dict[str, type] = field(default_factory=dict)
    required_fields: set[str] | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("JsonArtifactSpec.name must be non-empty")
        if not self.name.endswith(".json"):
            raise ValueError(f"JsonArtifactSpec.name must end with .json, got {self.name!r}")
        if self.required_fields is not None:
            unknown = self.required_fields - set(self.fields)
            if unknown:
                raise ValueError(f"required_fields {sorted(unknown)} not in declared fields")

    @property
    def required_field_names(self) -> set[str]:
        if self.required_fields is not None:
            return set(self.required_fields)
        return set(self.fields)


SectionInput = SectionSpec | str
JsonArtifactInput = JsonArtifactSpec | str


def _coerce_section(item: SectionInput) -> SectionSpec:
    return item if isinstance(item, SectionSpec) else SectionSpec(name=item)


def _coerce_json_artifact(item: JsonArtifactInput) -> JsonArtifactSpec:
    return item if isinstance(item, JsonArtifactSpec) else JsonArtifactSpec(name=item)


@dataclass
class ArtifactSchema:
    """Declarative shape of compiled artifacts on disk.

    Used by the writer to lay out files and validate extraction outputs and by
    the read-side ArtifactStore (T-09) to know what paths and field names are
    valid. See SPEC.md §7.1 and §8.1.
    """

    entity_path: str = DEFAULT_ENTITY_PATH
    sections: list[SectionSpec] = field(default_factory=list)
    json_artifacts: list[JsonArtifactSpec] = field(default_factory=list)
    raw_path: str = DEFAULT_RAW_PATH
    extraction_meta: str = DEFAULT_EXTRACTION_META
    text_extensions: frozenset[str] = DEFAULT_TEXT_EXTENSIONS
    version: str = "1"

    def __post_init__(self) -> None:
        self.sections = [_coerce_section(s) for s in self.sections]
        self.json_artifacts = [_coerce_json_artifact(j) for j in self.json_artifacts]

        if not parse_template_keys(self.entity_path):
            raise ValueError(
                f"entity_path {self.entity_path!r} must contain at least one {{placeholder}}"
            )

        names = [s.name for s in self.sections]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate section names in schema: {names}")

        json_names = [j.name for j in self.json_artifacts]
        if len(set(json_names)) != len(json_names):
            raise ValueError(f"duplicate json_artifact names in schema: {json_names}")

        for ext in self.text_extensions:
            if not ext.startswith("."):
                raise ValueError(f"text_extensions entry {ext!r} must start with '.'")

    # ---- Introspection used by writer + read-side --------------------------

    def entity_path_keys(self) -> tuple[str, ...]:
        return parse_template_keys(self.entity_path)

    def required_sections(self) -> list[SectionSpec]:
        return [s for s in self.sections if s.required and not s.is_glob]

    def section(self, name: str) -> SectionSpec | None:
        for s in self.sections:
            if s.name == name:
                return s
        for s in self.sections:
            if s.is_glob:
                prefix = s.name.split("*", 1)[0]
                if name.startswith(prefix):
                    return s
        return None

    def json_artifact(self, name: str) -> JsonArtifactSpec | None:
        for j in self.json_artifacts:
            if j.name == name:
                return j
        return None

    # ---- Constructors ------------------------------------------------------

    @classmethod
    def document_qa_default(cls) -> ArtifactSchema:
        """Default schema for the document_qa recipe (SPEC §17)."""
        return cls(
            entity_path=DEFAULT_ENTITY_PATH,
            sections=[
                SectionSpec(name="document_summary"),
                SectionSpec(name="sections/*"),
                SectionSpec(name="insights/*"),
            ],
            json_artifacts=[JsonArtifactSpec(name="metadata.json")],
        )

    @classmethod
    def generic_default(cls) -> ArtifactSchema:
        """Default schema for non-uniform / mixed corpora.

        Where :meth:`document_qa_default` assumes every document shares a shape,
        this offers corpus-agnostic sections any document can fill: one required
        summary slot, the rest optional. Use it when a single corpus mixes
        document kinds (a textbook, a law, a manual) that no fixed schema fits.

        Section targeting is weaker as a result — a document may leave most slots
        empty — so retrieval recovers the long tail via bm25 over the raw text
        rather than relying on well-populated sections.
        """
        return cls(
            entity_path=DEFAULT_ENTITY_PATH,
            sections=[
                SectionSpec(name="overview/topic_summary", required=True),
                SectionSpec(name="key_concepts"),
                SectionSpec(name="entities_and_definitions"),
                SectionSpec(name="structure/outline"),
                SectionSpec(name="notable_passages"),
                SectionSpec(name="citations/source_evidence"),
            ],
            json_artifacts=[JsonArtifactSpec(name="metadata.json")],
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> ArtifactSchema:
        data = yaml.safe_load(Path(path).read_text())
        if not isinstance(data, dict):
            raise ValueError(f"schema YAML must be a mapping, got {type(data).__name__}")
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> ArtifactSchema:
        sections = [_section_from_yaml(s) for s in data.get("sections", [])]
        json_artifacts = [_json_artifact_from_yaml(j) for j in data.get("json_artifacts", [])]
        text_ext_raw = data.get("text_extensions")
        text_extensions = (
            frozenset(text_ext_raw) if text_ext_raw is not None else DEFAULT_TEXT_EXTENSIONS
        )
        return cls(
            entity_path=data.get("entity_path", DEFAULT_ENTITY_PATH),
            sections=sections,
            json_artifacts=json_artifacts,
            raw_path=data.get("raw_path", DEFAULT_RAW_PATH),
            extraction_meta=data.get("extraction_meta", DEFAULT_EXTRACTION_META),
            text_extensions=text_extensions,
            version=str(data.get("version", "1")),
        )

    # ---- LLM-prompt helper (consumed by T-14 LLMExtractor) -----------------

    def to_json_schema(self) -> dict[str, Any]:
        """Return a JSON Schema describing the expected extraction output.

        The schema describes an object with two top-level keys: `sections`
        (mapping section name → str) and `json_artifacts` (mapping filename →
        object). T-14 (LLMExtractor) will consume this for its prompt template;
        the design here is intentionally minimal and may be refined when T-14
        lands.
        """
        return {
            "type": "object",
            "properties": {
                "sections": {
                    "type": "object",
                    "properties": {
                        s.name: {"type": "string"} for s in self.sections if not s.is_glob
                    },
                    "required": [s.name for s in self.required_sections()],
                    "additionalProperties": {"type": "string"},
                },
                "json_artifacts": {
                    "type": "object",
                    "properties": {j.name: _json_spec_to_schema(j) for j in self.json_artifacts},
                    "required": [j.name for j in self.json_artifacts],
                },
            },
            "required": ["sections", "json_artifacts"],
        }


# ---- JSON-schema + YAML helpers ------------------------------------------

_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _json_spec_to_schema(spec: JsonArtifactSpec) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            name: {"type": _TYPE_MAP.get(t, "string")} for name, t in spec.fields.items()
        },
        "required": sorted(spec.required_field_names),
    }


_TYPE_NAMES: dict[str, type] = {
    "str": str,
    "string": str,
    "int": int,
    "integer": int,
    "float": float,
    "number": float,
    "bool": bool,
    "boolean": bool,
    "list": list,
    "array": list,
    "dict": dict,
    "object": dict,
}


def _section_from_yaml(item: Any) -> SectionSpec:
    if isinstance(item, str):
        return SectionSpec(name=item)
    if isinstance(item, dict):
        return SectionSpec(
            name=item["name"],
            required=bool(item.get("required", False)),
            max_chars=item.get("max_chars"),
        )
    raise ValueError(f"section entry must be str or mapping, got {type(item).__name__}")


def _json_artifact_from_yaml(item: Any) -> JsonArtifactSpec:
    if isinstance(item, str):
        return JsonArtifactSpec(name=item)
    if isinstance(item, dict):
        fields_raw = item.get("fields") or {}
        fields_typed: dict[str, type] = {}
        for key, type_token in fields_raw.items():
            token = type_token if isinstance(type_token, str) else "string"
            if token not in _TYPE_NAMES:
                raise ValueError(f"unknown field type {type_token!r} for {key!r}")
            fields_typed[key] = _TYPE_NAMES[token]
        required_raw = item.get("required_fields")
        return JsonArtifactSpec(
            name=item["name"],
            fields=fields_typed,
            required_fields=set(required_raw) if required_raw is not None else None,
        )
    raise ValueError(f"json_artifact entry must be str or mapping, got {type(item).__name__}")
