# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

Reigner is an **early-stage** Python library for single-agent, retrieval-shaped, citation-faithful agents over compiled knowledge. The package skeleton (T-01) is in place — `pyproject.toml`, CI, lint/type/test toolchain, and empty subpackages — but the loop, tools, ingestion, and CLI commands are not yet implemented. The authoritative source of truth is `SPEC.md`; in-flight work and dependencies are tracked in `TASKS.md`.

## Core Design Documents

- **`SPEC.md`** — Full v0 specification: package layout, guardrails, API contracts, ingestion pipeline, event protocol, configuration schema, CLI commands, and the 8-week build order. Read this before writing any code.
- **`PRINCIPLES.md`** — Design rationale: why each architectural decision was made (11 principles). Consult when resolving ambiguity.
- **`AGENTS.md`** — Contributor guidelines: style rules, commit conventions, testing priorities.

## Architecture

Reigner is a **single-agent retrieval library**, not a coding agent or multi-agent orchestrator. Every design decision flows from this constraint.

### Core Loop (`reigner/harness/`)
The main event loop is intentionally ~300 lines. It embeds 11 numbered guardrails (G1–G11) covering context budgeting, tool result truncation, compaction, parallel read coalescing, and graceful failure. The loop must remain fully legible — no abstraction that hides control flow.

### Tool System (`reigner/tools/`)
Tools are decorated with `@tool` and organized into categories (`read`, `write`, `pseudo`, `domain`) and profiles (`full`, `read_only`, `eval`). Every tool result is **bounded and self-describing**: results include `has_more`, `truncated`, and `available_keys` so the model can request more without unbounded calls. The same `@tool` constraints make any tool MCP-exportable.

### Artifact System
Agents never touch raw files. Ingestion compiles raw documents → extracted artifacts stored in a schema-aware `ArtifactStore`. Agents query the compiled graph via `ArtifactStore`; `ArtifactWriter` is write-side only during ingestion.

### Ingestion Pipeline (`reigner/ingestion/`)
Three layers: schema contract (what to extract), LLM extractor (does the extraction), pipeline runner (orchestrates loaders/writers). Ingestion is a one-time compilation step, not a live process.

### Instruction file (`reigner/role/`)
Each Reigner project has one instruction file at its repo root: `./REIGNER.md`. This is the single runtime source of truth — there is **no cascade** across machine-global / project / recipe layers. The reasoning (SPEC §9): Reigner is a toolbox for shipping per-project agents (open source or to clients), so runtime behavior must be reproducible from the project repo. A machine-global file silently shaping a deployed agent is exactly the footgun this design rejects. Recipes are init-time scaffolds — they generate the project's REIGNER.md and then get out of the way. Skills (loaded on-demand mid-loop) are the only dynamic layer.

### Sessions (`reigner/sessions/`)
Sessions are durable JSONL files on disk under `./.reigner/sessions/` (project-local, not machine-global — same reproducibility argument as REIGNER.md). They are forkable and replayable, enabling A/B/C comparison of REIGNER.md / tool / model variants without re-running from scratch.

### Event Protocol
All output (CLI, web, MCP) consumes the same typed dataclass events: `StatusEvent`, `ToolCallEvent`, `ToolResultEvent`, `CitationEvent`, etc. Do not add output paths that bypass this protocol.

### Skills (`reigner/skills/`)
Instruction modules loaded on demand when the model invokes them. Not loaded at startup.

### Recipes (`reigner/recipes/`)
Two reference recipes ship with v0: `document_qa` (the hero use case) and `code_navigator` (contrast case). Recipes are **init-time scaffolds**, not runtime sources: their bundled `REIGNER.md`, `reigner.yaml`, `schema.yaml`, and extractor stub are copied verbatim into the user's project by `reigner init --recipe <name>`. After init the recipe is no longer referenced.

## Development Conventions

**Language**: Python 3.12+ with fully typed APIs throughout. No untyped public surfaces.

**Naming**: `snake_case` for modules and functions; `PascalCase` for classes.

**Package manager**: `uv` (e.g., `uv add reigner`).

**Commits**: Conventional Commits — `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.

**Constraint**: Do not port code from prior systems. All contracts are re-derived from SPEC.md. Keep SPEC.md and PRINCIPLES.md consistent with any implementation choices.

## Build & Test Commands

```bash
# Install dependencies (including all extras and dev group)
uv sync --all-extras --group dev

# Lint, format check, type check, tests — what CI runs
uv run ruff check .
uv run ruff format --check .
uv run mypy reigner
uv run pytest

# Run a single test file
uv run pytest tests/path/to/test_file.py

# CLI entry point
uv run reigner --help
```

Testing priorities (per `AGENTS.md`): bounded outputs, citations, sessions, truncation, compaction.

## Planned CLI Commands

```
reigner init      # scaffold a project (--guided default, or --recipe / --blank)
reigner ingest    # compile raw documents into artifacts
reigner chat      # interactive chat session
reigner eval      # run eval suite
reigner inspect   # inspect sessions/artifacts/role/tools
reigner session   # manage sessions (fork, diff, replay)
reigner serve     # start MCP/HTTP server
```

## Out of Scope (Do Not Implement)

Per `PRINCIPLES.md` §11 and `SPEC.md` §19:
- Multi-agent orchestration
- Code execution / sandboxing
- Write access to the user's filesystem during agent runtime
- Fine-tuning or model training
- Real-time data sources
- GUI or desktop app
