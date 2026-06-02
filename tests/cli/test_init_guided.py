"""Behavior tests for `reigner init` guided (default) mode.

A stub adapter and monkeypatched prompts drive the whole flow with no live
model call and no real keystrokes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
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
    answers: tuple[str, ...] = ("Finance filings", "PDFs", "metric lookups", "strict"),
    confirm: bool = True,
    adapter: StubAdapter | None = None,
    env_key: str | None = "ANTHROPIC_API_KEY",
):
    for k in _KEYS:
        monkeypatch.delenv(k, raising=False)
    if env_key:
        monkeypatch.setenv(env_key, "test-key")

    stub = adapter or StubAdapter()
    monkeypatch.setattr("reigner.harness.agent._build_adapter", lambda provider, model: stub)

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


def test_strip_fences_unwraps_markdown_block() -> None:
    from reigner.cli._guided import _strip_fences

    wrapped = "```yaml\nentity_path: a\n```"
    assert _strip_fences(wrapped) == "entity_path: a\n"
    assert _strip_fences("plain\ntext") == "plain\ntext\n"
