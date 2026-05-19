"""Behavior tests for `reigner ingest` (T-20).

The CLI itself is exercised end-to-end with Typer's CliRunner. We avoid
running a real LLM extractor — tests build an in-process IngestionPipeline
with a stub Transform + Loader and import it via a tiny site-package the
test creates on the fly.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reigner.cli.__main__ import app

runner = CliRunner()


def _run(args: list[str], cwd: Path):
    old = os.getcwd()
    os.chdir(cwd)
    saved_path = list(sys.path)
    saved_modules = set(sys.modules)
    try:
        return runner.invoke(app, args, catch_exceptions=False)
    finally:
        os.chdir(old)
        sys.path[:] = saved_path
        # Drop any modules the CLI may have imported from cwd so the next test
        # starts clean.
        for mod in set(sys.modules) - saved_modules:
            sys.modules.pop(mod, None)


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    """A minimal project: extractors package + a stub pipeline + raw dir."""
    (tmp_path / "extractors").mkdir()
    (tmp_path / "extractors" / "__init__.py").write_text("")
    (tmp_path / "library" / "raw").mkdir(parents=True)
    (tmp_path / "library" / "raw" / "doc.md").write_text("# hello\n")
    yield tmp_path


def _write_stub_pipeline(project: Path, *, attr: str = "pipeline") -> None:
    """Write a minimal IngestionPipeline whose transform/writer no-op."""
    body = textwrap.dedent(
        f"""
        from pathlib import Path
        from reigner.ingestion import IngestionPipeline
        from reigner.ingestion.loaders import LoadedDocument

        class _Loader:
            extensions = frozenset({{".md"}})
            async def load(self, src: Path) -> LoadedDocument:
                return LoadedDocument(
                    raw=src.read_bytes(),
                    meta={{"identifiers": {{}}}},
                )

        class _Transform:
            async def run(self, raw, meta):
                from reigner.ingestion import ExtractionResult
                return ExtractionResult(sections={{}}, json_artifacts={{}}, meta={{}})
            def cache_key(self, raw):
                return "stub"

        class _Writer:
            async def write(self, *, loaded, result, identifiers):
                return None

        {attr} = IngestionPipeline(
            loaders=[_Loader()],
            transforms=[_Transform()],
            writers=[_Writer()],
            concurrency=1,
            on_error="skip",
        )
        """
    )
    (project / "extractors" / "pipeline.py").write_text(body)


# ---------------------------------------------------------------------------
# Pipeline resolution
# ---------------------------------------------------------------------------


def test_convention_default_runs(project: Path) -> None:
    _write_stub_pipeline(project)
    result = _run(["ingest"], project)
    assert result.exit_code == 0, result.output
    assert "ingestion complete" in result.stdout


def test_pipeline_flag_requires_source(project: Path) -> None:
    _write_stub_pipeline(project)
    result = _run(["ingest", "--pipeline", "extractors.pipeline:pipeline"], project)
    assert result.exit_code == 2
    assert "--source is required" in result.output


def test_pipeline_flag_with_source_runs(project: Path) -> None:
    _write_stub_pipeline(project)
    result = _run(
        [
            "ingest",
            "--pipeline",
            "extractors.pipeline:pipeline",
            "--source",
            "library/raw",
        ],
        project,
    )
    assert result.exit_code == 0


def test_pipeline_bad_format(project: Path) -> None:
    result = _run(["ingest", "--pipeline", "no_colon", "--source", "library/raw"], project)
    assert result.exit_code == 2
    assert "module:object" in result.output


def test_pipeline_missing_module(project: Path) -> None:
    result = _run(
        ["ingest", "--pipeline", "no_such_pkg.no_mod:pipeline", "--source", "library/raw"],
        project,
    )
    assert result.exit_code == 2
    assert "could not import" in result.output


def test_pipeline_missing_attribute(project: Path) -> None:
    _write_stub_pipeline(project)
    result = _run(
        [
            "ingest",
            "--pipeline",
            "extractors.pipeline:not_the_pipeline",
            "--source",
            "library/raw",
        ],
        project,
    )
    assert result.exit_code == 2
    assert "no attribute" in result.output
    assert "pipeline" in result.output  # listed in 'available'


def test_pipeline_wrong_type(project: Path, tmp_path: Path) -> None:
    (project / "extractors" / "pipeline.py").write_text("pipeline = 42\n")
    result = _run(["ingest"], project)
    assert result.exit_code == 2
    assert "expected IngestionPipeline" in result.output


# ---------------------------------------------------------------------------
# --dry-run / --json
# ---------------------------------------------------------------------------


def test_dry_run_lists_sources_without_writing(project: Path) -> None:
    _write_stub_pipeline(project)
    result = _run(["ingest", "--dry-run"], project)
    assert result.exit_code == 0
    assert "would ingest" in result.stdout
    assert "doc.md" in result.stdout
    assert "ingestion complete" not in result.stdout  # didn't run


def test_json_mode_emits_ndjson(project: Path) -> None:
    _write_stub_pipeline(project)
    result = _run(["ingest", "--json"], project)
    assert result.exit_code == 0
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert lines, "expected at least one NDJSON line"
    for ln in lines:
        json.loads(ln)  # every line is a valid JSON event


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def test_concurrency_override(project: Path) -> None:
    _write_stub_pipeline(project)
    result = _run(["ingest", "--concurrency", "2"], project)
    assert result.exit_code == 0
    assert "concurrency 2" in result.stdout


def test_on_error_override(project: Path) -> None:
    _write_stub_pipeline(project)
    result = _run(["ingest", "--on-error", "raise"], project)
    assert result.exit_code == 0
    assert "on_error=raise" in result.stdout


def test_on_error_invalid(project: Path) -> None:
    _write_stub_pipeline(project)
    result = _run(["ingest", "--on-error", "bogus"], project)
    assert result.exit_code == 2
    assert "raise|skip|dead_letter" in result.output
