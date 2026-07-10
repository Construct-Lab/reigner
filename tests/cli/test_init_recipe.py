"""Behavior tests for `reigner init --recipe document_qa`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from reigner.artifacts import ArtifactSchema
from reigner.cli.__main__ import app
from reigner.config import ReignerConfig
from reigner.harness.agent import Harness

# The recipe produces the shared blank layout plus a tuned reigner.yaml.
EXPECTED_PATHS = {
    "REIGNER.md",
    "reigner.yaml",
    "schema.yaml",
    "extractors/__init__.py",
    "extractors/my_extractor.py",
    "extractors/pipeline.py",
    "library/raw",
    "library/artifacts",
    "search-index",
    "eval/cases.yaml",
    ".env.example",
    ".gitignore",
    "README.md",
}

runner = CliRunner()


def _run(args: list[str], cwd: Path):
    """Invoke the CLI with cwd set to a tmp dir — keeps scaffolding hermetic."""
    import os

    old = os.getcwd()
    os.chdir(cwd)
    try:
        return runner.invoke(app, args)
    finally:
        os.chdir(old)


def _present(target: Path) -> set[str]:
    return {p.relative_to(target).as_posix() for p in target.rglob("*")}


def test_recipe_scaffolds_expected_tree(tmp_path: Path) -> None:
    result = _run(["init", "demo", "--recipe", "document_qa"], tmp_path)
    assert result.exit_code == 0, result.stdout + result.stderr
    present = _present(tmp_path / "demo")
    missing = EXPECTED_PATHS - present
    assert not missing, f"missing scaffold paths: {missing}"


def test_recipe_config_is_the_tuned_one(tmp_path: Path) -> None:
    _run(["init", "demo", "--recipe", "document_qa"], tmp_path)
    cfg = ReignerConfig.load(tmp_path / "demo" / "reigner.yaml")
    # The recipe's config, not the generated blank default.
    assert cfg.name == "document_qa"
    assert cfg.model.provider == "openai"
    assert cfg.oracle is not None
    assert cfg.tools.artifacts is not None
    assert cfg.tools.search is not None
    assert cfg.role.skills == [
        "citation_strict",
        "clarify_when_ambiguous",
        "targeted_retrieval",
    ]


def test_recipe_config_builds_a_harness(tmp_path: Path) -> None:
    _run(["init", "demo", "--recipe", "document_qa"], tmp_path)
    harness = Harness.from_config(tmp_path / "demo" / "reigner.yaml")
    names = {spec.name for spec in harness.registry}
    # Artifact tools, search tools, and the oracle escalation are all wired.
    assert {"read_artifact_file", "get_json_field", "list_documents"} <= names
    assert {"bm25_search", "filtered_search", "section_search"} <= names
    assert "escalate_to_oracle" in names
    assert harness.oracle_adapter is not None


def test_bundled_schema_matches_default(tmp_path: Path) -> None:
    # The copied schema.yaml must equal document_qa_default() so the CLI-copied
    # schema and the code-derived one can never diverge.
    _run(["init", "demo", "--recipe", "document_qa"], tmp_path)
    bundled = ArtifactSchema.from_yaml(tmp_path / "demo" / "schema.yaml")
    assert bundled == ArtifactSchema.document_qa_default()


def test_recipe_extractor_stub_is_copied(tmp_path: Path) -> None:
    _run(["init", "demo", "--recipe", "document_qa"], tmp_path)
    stub = (tmp_path / "demo" / "extractors" / "my_extractor.py").read_text()
    assert "class MyExtractor(LLMExtractor)" in stub
    assert "MapReduceExtractor" in stub  # points at the graduation path


def test_recipe_pipeline_is_wired_not_commented(tmp_path: Path) -> None:
    # Unlike the blank stub, the recipe ships a runnable pipeline matching its
    # schema — live code, and it supplies entity_id/version for entity_path.
    _run(["init", "demo", "--recipe", "document_qa"], tmp_path)
    pipeline = (tmp_path / "demo" / "extractors" / "pipeline.py").read_text()
    assert "pipeline = IngestionPipeline(" in pipeline  # not commented out
    assert "from .my_extractor import MyExtractor" in pipeline
    assert "def derive_identifiers(" in pipeline
    assert '"entity_id"' in pipeline and '"version"' in pipeline
    compile(pipeline, "pipeline.py", "exec")  # parses as real Python


def test_unknown_recipe_fails_loudly(tmp_path: Path) -> None:
    result = _run(["init", "demo", "--recipe", "nope"], tmp_path)
    assert result.exit_code == 2
    assert "unknown recipe" in result.stderr
    assert "document_qa" in result.stderr  # lists what is available
    assert not (tmp_path / "demo").exists()
