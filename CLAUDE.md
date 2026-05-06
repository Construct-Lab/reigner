# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

Reigner is a **pre-implementation** Python library for single-agent, retrieval-shaped, citation-faithful agents over compiled knowledge. The repository currently contains only design documents; no source code exists yet. The authoritative source of truth is `SPEC.md`.

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

### ROLE Cascade (`reigner/roles/`)
Instructions merge at runtime in priority order: package defaults → user global (`~/.reigner/`) → project local (`.reigner/`) → recipe-specific. Later layers override earlier ones.

### Sessions (`reigner/sessions/`)
Sessions are durable JSONL files on disk. They are forkable and replayable, enabling A/B/C comparison of ROLE/tool/model variants without re-running from scratch.

### Event Protocol
All output (CLI, web, MCP) consumes the same typed dataclass events: `StatusEvent`, `ToolCallEvent`, `ToolResultEvent`, `CitationEvent`, etc. Do not add output paths that bypass this protocol.

### Skills (`reigner/skills/`)
Instruction modules loaded on demand when the model invokes them. Not loaded at startup.

### Recipes (`reigner/recipes/`)
Two reference recipes ship with v0: `document_qa` (the hero use case) and `code_navigator` (contrast case). Recipes are composable ROLE + tool profiles.

## Development Conventions

**Language**: Python 3.12+ with fully typed APIs throughout. No untyped public surfaces.

**Naming**: `snake_case` for modules and functions; `PascalCase` for classes.

**Package manager**: `uv` (e.g., `uv add reigner`).

**Commits**: Conventional Commits — `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.

**Constraint**: Do not port code from prior systems. All contracts are re-derived from SPEC.md. Keep SPEC.md and PRINCIPLES.md consistent with any implementation choices.

## Build & Test Commands

No source code exists yet. When implementation begins:

```bash
# Install dependencies
uv sync

# Run tests
python -m pytest

# Run a single test file
python -m pytest tests/path/to/test_file.py

# CLI entry point
python -m reigner.cli
```

Testing priorities (per `AGENTS.md`): bounded outputs, citations, sessions, truncation, compaction.

## Planned CLI Commands

```
reigner init      # initialize a project
reigner ingest    # compile raw documents into artifacts
reigner chat      # interactive chat session
reigner eval      # run eval suite
reigner inspect   # inspect sessions/artifacts
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
