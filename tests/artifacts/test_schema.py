from __future__ import annotations

from pathlib import Path

import pytest

from reigner.artifacts.schema import (
    ArtifactSchema,
    JsonArtifactSpec,
    SectionSpec,
)


def test_section_spec_defaults() -> None:
    spec = SectionSpec(name="x")
    assert spec.required is False
    assert spec.max_chars is None
    assert spec.is_glob is False


def test_section_spec_glob_detected() -> None:
    assert SectionSpec(name="sections/*").is_glob


def test_section_spec_glob_cannot_be_required() -> None:
    with pytest.raises(ValueError, match="cannot be required"):
        SectionSpec(name="sections/*", required=True)


def test_section_spec_max_chars_positive() -> None:
    with pytest.raises(ValueError, match="max_chars"):
        SectionSpec(name="x", max_chars=0)


def test_json_artifact_spec_must_end_with_json() -> None:
    with pytest.raises(ValueError, match="must end with .json"):
        JsonArtifactSpec(name="metadata.txt")


def test_json_artifact_spec_required_fields_must_be_declared() -> None:
    with pytest.raises(ValueError, match="not in declared fields"):
        JsonArtifactSpec(name="x.json", fields={"a": str}, required_fields={"a", "b"})


def test_json_artifact_required_field_names_defaults_to_all() -> None:
    spec = JsonArtifactSpec(name="x.json", fields={"a": str, "b": int})
    assert spec.required_field_names == {"a", "b"}


def test_json_artifact_required_field_names_explicit() -> None:
    spec = JsonArtifactSpec(name="x.json", fields={"a": str, "b": int}, required_fields={"a"})
    assert spec.required_field_names == {"a"}


def test_schema_bare_strings_coerce() -> None:
    schema = ArtifactSchema(
        sections=["a", "b"],  # type: ignore[list-item]
        json_artifacts=["x.json"],  # type: ignore[list-item]
    )
    assert schema.sections == [SectionSpec(name="a"), SectionSpec(name="b")]
    assert schema.json_artifacts == [JsonArtifactSpec(name="x.json")]


def test_schema_entity_path_keys() -> None:
    schema = ArtifactSchema(entity_path="{ticker}/{fiscal_year}")
    assert schema.entity_path_keys() == ("ticker", "fiscal_year")


def test_schema_entity_path_must_have_placeholders() -> None:
    with pytest.raises(ValueError, match="placeholder"):
        ArtifactSchema(entity_path="static")


def test_schema_rejects_duplicate_sections() -> None:
    with pytest.raises(ValueError, match="duplicate section"):
        ArtifactSchema(sections=[SectionSpec(name="a"), SectionSpec(name="a")])


def test_schema_rejects_duplicate_json_artifacts() -> None:
    with pytest.raises(ValueError, match="duplicate json"):
        ArtifactSchema(
            json_artifacts=[
                JsonArtifactSpec(name="a.json"),
                JsonArtifactSpec(name="a.json"),
            ],
        )


def test_schema_text_extensions_must_start_with_dot() -> None:
    with pytest.raises(ValueError, match="must start with"):
        ArtifactSchema(text_extensions=frozenset({"md"}))


def test_schema_section_lookup_exact() -> None:
    schema = ArtifactSchema(sections=[SectionSpec(name="document_summary")])
    assert schema.section("document_summary") is not None
    assert schema.section("missing") is None


def test_schema_section_lookup_glob() -> None:
    schema = ArtifactSchema(sections=[SectionSpec(name="sections/*")])
    matched = schema.section("sections/business")
    assert matched is not None and matched.name == "sections/*"


def test_schema_required_sections_excludes_globs() -> None:
    schema = ArtifactSchema(
        sections=[
            SectionSpec(name="document_summary", required=True),
            SectionSpec(name="sections/*"),
        ],
    )
    required = schema.required_sections()
    assert [s.name for s in required] == ["document_summary"]


def test_document_qa_default_loads() -> None:
    schema = ArtifactSchema.document_qa_default()
    assert schema.section("document_summary") is not None
    assert schema.section("sections/business") is not None
    assert schema.json_artifact("metadata.json") is not None


def test_to_json_schema_basic_shape() -> None:
    schema = ArtifactSchema(
        sections=[SectionSpec(name="document_summary", required=True)],
        json_artifacts=[
            JsonArtifactSpec(name="metadata.json", fields={"ticker": str}),
        ],
    )
    js = schema.to_json_schema()
    assert js["type"] == "object"
    assert js["required"] == ["sections", "json_artifacts"]
    assert "document_summary" in js["properties"]["sections"]["properties"]
    assert js["properties"]["sections"]["required"] == ["document_summary"]
    metadata_schema = js["properties"]["json_artifacts"]["properties"]["metadata.json"]
    assert metadata_schema["properties"]["ticker"] == {"type": "string"}
    assert metadata_schema["required"] == ["ticker"]


def test_from_yaml_round_trip(tmp_path: Path) -> None:
    yaml_text = """
entity_path: "{ticker}/{fiscal_year}"
sections:
  - document_summary
  - name: sections/business
    required: true
    max_chars: 5000
json_artifacts:
  - name: metadata.json
    fields:
      ticker: string
      fiscal_year: integer
    required_fields: [ticker]
text_extensions: [".md", ".txt"]
version: "2"
"""
    path = tmp_path / "schema.yaml"
    path.write_text(yaml_text)
    schema = ArtifactSchema.from_yaml(path)
    assert schema.entity_path == "{ticker}/{fiscal_year}"
    assert schema.version == "2"
    business = schema.section("sections/business")
    assert business is not None and business.required and business.max_chars == 5000
    metadata = schema.json_artifact("metadata.json")
    assert metadata is not None
    assert metadata.fields == {"ticker": str, "fiscal_year": int}
    assert metadata.required_field_names == {"ticker"}
    assert schema.text_extensions == frozenset({".md", ".txt"})


def test_from_yaml_rejects_non_mapping(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError, match="must be a mapping"):
        ArtifactSchema.from_yaml(path)
