# Repository Guidelines

## Project Structure & Module Organization

Reigner is a Python 3.12+ harness for retrieval-shaped, citation-faithful question-answering agents. Treat `SPEC.md` as the source of truth for the package design and `PRINCIPLES.md` as the rationale behind architectural choices.

The source tree is `reigner/`, with core loop code under `reigner/harness/`, tool definitions under `reigner/tools/`, ingestion helpers under `reigner/ingestion/`, recipes under `reigner/recipes/`, CLI commands under `reigner/cli/`, the HTTP server under `reigner/server/`, and evaluation code under `reigner/eval/`. Tests mirror the package layout under `tests/`, for example `tests/harness/test_loop.py`.

## Build, Test, and Development Commands

The project uses `uv`. Install with `uv sync --all-extras --group dev`, then:

- `uv run ruff check .`: lint.
- `uv run ruff format --check .`: format check.
- `uv run mypy reigner`: type check.
- `uv run pytest`: full test suite. Pass a path to run one file.
- `uv run reigner --help`: CLI entry point.

The first four are what CI runs; run them before opening a pull request.

## Coding Style & Naming Conventions

Target Python 3.12+. Use typed public APIs, dataclasses or Pydantic-style schemas where structured contracts matter, and async functions for model/tool loops. Keep modules small and aligned with the `SPEC.md` package map.

Use `snake_case` for modules, functions, variables, and tool names; `PascalCase` for classes; and explicit names for events, stores, registries, and adapters, such as `CitationEvent`, `ArtifactStore`, and `ToolRegistry`.

## Testing Guidelines

Use `pytest` for unit and integration tests. Prioritize tests around bounded tool outputs, citation provenance, session replay/forking, truncation, compaction, and CLI wrappers. Name test files `test_<module>.py` and test functions `test_<behavior>()`.

## Commit & Pull Request Guidelines

Git history currently uses Conventional Commits, for example `feat: initial commit`. Continue with `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, and `chore:` prefixes.

Pull requests should describe the behavior or document change, link related issues when available, and note any tests run. For documentation-only changes, include a short summary of which design contract changed and whether `SPEC.md` and `PRINCIPLES.md` remain consistent.

## Agent-Specific Instructions

Keep `SPEC.md` and `PRINCIPLES.md` in agreement. If they conflict, surface it explicitly instead of silently choosing one. Do not import or copy predecessor code; the principles require fresh implementation, with prior systems used only for comparison after a draft exists.
