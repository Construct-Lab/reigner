"""Behavior tests for `reigner init` guided (default) mode.

A stub adapter and monkeypatched prompts drive the whole flow with no live
model call and no real keystrokes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from rich.console import Console
from typer.testing import CliRunner

from reigner.cli.__main__ import app
from reigner.config import ReignerConfig
from reigner.harness.adapters.base import ModelAction, TokenUsage

runner = CliRunner()

_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")

_ROLE_MD = "# REIGNER.md\n\n## Identity\nA test agent over the stated domain.\n"

_VALID_SCHEMA = """\
entity_path: "{entity_id}/{version}"
sections:
  - name: document_summary
    required: true
    max_chars: 2000
json_artifacts:
  - name: metadata.json
    fields:
      entity_id: str
      version: str
"""

# Unknown field type → ArtifactSchema.from_yaml raises, exercising the retry.
_INVALID_SCHEMA = """\
entity_path: "{entity_id}/{version}"
json_artifacts:
  - name: metadata.json
    fields:
      revenue: notatype
"""

# A model-shaped schema for the mixed branch: domain sections default to
# required:true, and one collides with the generic baseline (overview/...) to
# exercise dedup.
_DOMAIN_SCHEMA = """\
entity_path: "{topic}/{version}"
sections:
  - name: overview/topic_summary
    required: true
  - name: constitution/fundamental_rights
    required: true
    max_chars: 3500
  - name: judiciary/court_structure
    required: true
json_artifacts:
  - name: topic_metadata.json
    fields:
      topic: str
"""


class StubAdapter:
    """Returns canned text, routed by which system prompt it sees."""

    name = "anthropic"
    model = "claude-opus-4-7"
    supports_prompt_caching = True

    def __init__(
        self, role_text: str = _ROLE_MD, schema_texts: tuple[str, ...] = (_VALID_SCHEMA,)
    ) -> None:
        self.role_text = role_text
        self._schema_texts = list(schema_texts)
        self.calls: list[str] = []

    async def call(self, prompt: Any, tools: Any) -> ModelAction:
        self.calls.append(prompt.stable)
        text = self.role_text if "REIGNER.md" in prompt.stable else self._schema_texts.pop(0)
        return ModelAction(is_final_answer=True, text=text, usage=TokenUsage.empty())


def _drive(
    args: list[str],
    cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    answers: tuple[str, ...] = ("Finance filings", "PDFs", "metric lookups", "strict", "uniform"),
    confirm: bool = True,
    adapter: StubAdapter | None = None,
    env_key: str | None = "ANTHROPIC_API_KEY",
):
    for k in _KEYS:
        monkeypatch.delenv(k, raising=False)
    if env_key:
        monkeypatch.setenv(env_key, "test-key")

    stub = adapter or StubAdapter()
    monkeypatch.setattr("reigner.harness.adapters.build_adapter", lambda provider, model: stub)

    answer_iter = iter(answers)
    monkeypatch.setattr("reigner.cli._guided.RichPrompt.ask", lambda *a, **k: next(answer_iter))
    monkeypatch.setattr("reigner.cli._guided.typer.confirm", lambda *a, **k: confirm)

    old = os.getcwd()
    os.chdir(cwd)
    try:
        result = runner.invoke(app, args)
    finally:
        os.chdir(old)
    return result, stub


def test_bare_init_runs_guided_and_scaffolds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, stub = _drive(["init", "demo"], tmp_path, monkeypatch)
    assert result.exit_code == 0, result.stdout
    target = tmp_path / "demo"

    assert (target / "REIGNER.md").read_text() == _ROLE_MD
    # schema.yaml is the generated content and loads without raising.
    cfg = ReignerConfig.load(target / "reigner.yaml")
    assert cfg.name == "demo"
    from reigner.artifacts.schema import ArtifactSchema

    ArtifactSchema.from_yaml(target / "schema.yaml")
    # Gate accepted → the code-bearing stub is present.
    assert (target / "extractors" / "my_extractor.py").exists()
    assert "guided mode" in result.stdout
    # One role call + one schema call.
    assert len(stub.calls) == 2


def test_explicit_guided_flag_matches_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, _ = _drive(["init", "demo", "--guided"], tmp_path, monkeypatch)
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "demo" / "REIGNER.md").exists()


def test_gate_declined_skips_only_extractor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, _ = _drive(["init", "demo"], tmp_path, monkeypatch, confirm=False)
    assert result.exit_code == 0, result.stdout
    target = tmp_path / "demo"
    # The one code-bearing file is skipped …
    assert not (target / "extractors" / "my_extractor.py").exists()
    # … but the rest of the extractors package and generated files remain.
    assert (target / "extractors" / "__init__.py").exists()
    assert (target / "extractors" / "pipeline.py").exists()
    assert (target / "REIGNER.md").exists()
    assert (target / "schema.yaml").exists()


def test_no_api_key_prints_instructions_and_exits_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, stub = _drive(["init", "demo"], tmp_path, monkeypatch, env_key=None)
    assert result.exit_code == 0
    assert "ANTHROPIC_API_KEY" in result.stdout
    assert "blank" in result.stdout
    # Nothing scaffolded, no model call.
    assert not (tmp_path / "demo").exists()
    assert stub.calls == []


def test_invalid_schema_retries_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = StubAdapter(schema_texts=(_INVALID_SCHEMA, _VALID_SCHEMA))
    result, stub = _drive(["init", "demo"], tmp_path, monkeypatch, adapter=stub)
    assert result.exit_code == 0, result.stdout
    from reigner.artifacts.schema import ArtifactSchema

    ArtifactSchema.from_yaml(tmp_path / "demo" / "schema.yaml")
    # role + 2 schema attempts.
    assert len(stub.calls) == 3


def test_invalid_schema_twice_gives_up_without_scaffolding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = StubAdapter(schema_texts=(_INVALID_SCHEMA, _INVALID_SCHEMA))
    result, _ = _drive(["init", "demo"], tmp_path, monkeypatch, adapter=stub)
    assert result.exit_code == 1
    assert "valid schema.yaml" in result.stderr
    assert not (tmp_path / "demo").exists()


def test_collision_refuses_before_questions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "stray.txt").write_text("user data")
    stub = StubAdapter()
    result, stub = _drive(["init", "demo"], tmp_path, monkeypatch, adapter=stub)
    assert result.exit_code == 1
    assert "already exists" in result.stderr
    # Bailed before any model call.
    assert stub.calls == []
    assert (tmp_path / "demo" / "stray.txt").read_text() == "user data"


def test_detect_provider_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    from reigner.cli._guided import _detect_provider

    for k in _KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    # Anthropic wins on order even with OpenAI also present.
    assert _detect_provider() == ("anthropic", "claude-sonnet-4-6")


def test_detect_provider_gemini_google_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    from reigner.cli._guided import _detect_provider

    for k in _KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    assert _detect_provider() == ("gemini", "gemini-3.5-flash")


def test_guided_asks_uniformity(monkeypatch: pytest.MonkeyPatch) -> None:
    """The interview collects a fifth answer — corpus uniformity."""
    from reigner.cli._guided import GuidedAnswers, _collect_answers

    answers = iter(("Law", "PDFs", "Q&A", "strict", "mixed"))
    monkeypatch.setattr("reigner.cli._guided.RichPrompt.ask", lambda *a, **k: next(answers))
    result = _collect_answers(Console())
    assert isinstance(result, GuidedAnswers)
    assert result.uniformity == "mixed"


def test_mixed_yields_layered_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """mixed → one required summary + optional generic baseline + optional,
    deduped domain sections."""
    stub = StubAdapter(schema_texts=(_DOMAIN_SCHEMA,))
    answers = ("Indian law", "primer, constitution, manual", "beginner Q&A", "strict", "mixed")
    result, _ = _drive(["init", "demo"], tmp_path, monkeypatch, answers=answers, adapter=stub)
    assert result.exit_code == 0, result.stdout

    from reigner.artifacts.schema import ArtifactSchema

    schema = ArtifactSchema.from_yaml(tmp_path / "demo" / "schema.yaml")
    by_name = {s.name: s for s in schema.sections}

    # Exactly one required section, the universal summary.
    required = [s.name for s in schema.sections if s.required]
    assert required == ["overview/topic_summary"]

    # The generic baseline is present …
    assert "key_concepts" in by_name
    assert "notable_passages" in by_name
    # … and the domain sections survived, but forced optional.
    assert by_name["constitution/fundamental_rights"].required is False
    assert by_name["judiciary/court_structure"].required is False
    # Domain max_chars is preserved through the merge.
    assert by_name["constitution/fundamental_rights"].max_chars == 3500
    # The colliding domain section did not duplicate the baseline summary.
    assert sum(1 for s in schema.sections if s.name == "overview/topic_summary") == 1
    # entity_path comes from the model untouched.
    assert schema.entity_path == "{topic}/{version}"
    # json_artifacts survive, but their fields are relaxed so a partial document
    # never dead-letters — the field stays declared/typed, just not required.
    meta = next(j for j in schema.json_artifacts if j.name == "topic_metadata.json")
    assert "topic" in meta.fields
    assert meta.required_field_names == set()


def test_mixed_with_extractor_scaffolds_mapreduce_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = StubAdapter(schema_texts=(_DOMAIN_SCHEMA,))
    answers = ("Indian law", "mixed docs", "Q&A", "strict", "mixed")
    result, _ = _drive(
        ["init", "demo"], tmp_path, monkeypatch, answers=answers, adapter=stub, confirm=True
    )
    assert result.exit_code == 0, result.stdout
    extractor = (tmp_path / "demo" / "extractors" / "my_extractor.py").read_text()
    assert "MapReduceExtractor" in extractor
    assert "MAP_PROMPT" in extractor and "REDUCE_PROMPT" in extractor


def test_uniform_with_extractor_keeps_single_shot_stub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The uniform path is unchanged — the single-shot stub, not map-reduce."""
    result, _ = _drive(["init", "demo"], tmp_path, monkeypatch, confirm=True)
    assert result.exit_code == 0, result.stdout
    extractor = (tmp_path / "demo" / "extractors" / "my_extractor.py").read_text()
    assert "MapReduceExtractor" not in extractor


def test_uniform_schema_is_not_layered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """uniform keeps the model schema verbatim — no generic baseline injected."""
    result, _ = _drive(["init", "demo"], tmp_path, monkeypatch)
    assert result.exit_code == 0, result.stdout
    from reigner.artifacts.schema import ArtifactSchema

    schema = ArtifactSchema.from_yaml(tmp_path / "demo" / "schema.yaml")
    names = {s.name for s in schema.sections}
    assert names == {"document_summary"}  # exactly the model's _VALID_SCHEMA
    assert "key_concepts" not in names


def test_layer_mixed_schema_forces_optional_and_dedups() -> None:
    """Unit test for the dict-level merge, independent of the CLI flow."""
    from reigner.cli._guided import _layer_mixed_schema

    merged = yaml.safe_load(_layer_mixed_schema(_DOMAIN_SCHEMA))
    sections = merged["sections"]
    required = [s["name"] for s in sections if s.get("required")]
    assert required == ["overview/topic_summary"]
    names = [s["name"] for s in sections]
    assert names.count("overview/topic_summary") == 1  # deduped
    assert "key_concepts" in names  # baseline prepended
    domain = next(s for s in sections if s["name"] == "judiciary/court_structure")
    assert domain["required"] is False
    # JSON artifacts with declared fields are relaxed to never-required.
    artifact = next(j for j in merged["json_artifacts"] if j["name"] == "topic_metadata.json")
    assert artifact["required_fields"] == []


def test_strip_fences_unwraps_markdown_block() -> None:
    from reigner.cli._guided import _strip_fences

    wrapped = "```yaml\nentity_path: a\n```"
    assert _strip_fences(wrapped) == "entity_path: a\n"
    assert _strip_fences("plain\ntext") == "plain\ntext\n"
