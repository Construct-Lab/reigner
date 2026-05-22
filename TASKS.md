# Reigner — Implementation Tasks

All tasks have corresponding GitHub issues at https://github.com/Construct-Lab/reigner/issues.
Issue numbers match task numbers (T-01 = #1, T-02 = #2, etc.).

Tasks are organized into two phases. Phase 1 builds all individual components across five parallel
tracks. Phase 2 wires them together into recipes, skills, and a shippable example.

Each task lists its direct dependencies. A task is ready to start when all its dependencies are merged.

---

## How to read this

- **Depends on**: issues that must be merged before this one can start
- **Coordinate with**: no hard code dependency, but agree on the interface before writing code
- `S` / `M` / `L` — rough size (S = hours, M = 1–2 days, L = 3+ days)

---

## Phase 0 — Setup

Everyone is blocked on this. One person does it, then all five tracks can start.

- [ ] **[T-01 #1](https://github.com/Construct-Lab/reigner/issues/1)** `chore: initialize Python package` `L`
  - `pyproject.toml` with `uv`, entry points, dev dependencies (`pytest`, `ruff`, `mypy`)
  - `tests/` directory skeleton mirroring `reigner/` package layout
  - `.github/workflows/ci.yml` — on every PR: `uv sync` → `ruff check` → `mypy` → `pytest`
  - _Unblocks every other task_

---

## Phase 1 — Build the Parts

### Track A — Harness Core

- [ ] **[T-02 #2](https://github.com/Construct-Lab/reigner/issues/2)** `feat: typed event protocol` `S`
  - `harness/events.py`: all 10 event dataclasses
  - Depends on: #1
  - _Unblocks #3, #4, #5, #24_

- [ ] **[T-03 #3](https://github.com/Construct-Lab/reigner/issues/3)** `feat: AgentState` `M`
  - `harness/state.py`: history, scratchpad, token budgets, context pressure, `build_prompt`, `refresh_context`
  - Depends on: #2

- [ ] **[T-04 #4](https://github.com/Construct-Lab/reigner/issues/4)** `feat: model adapters` `M`
  - `harness/adapters/`: `ModelAdapter` protocol, Anthropic, OpenAI, Gemini implementations
  - Depends on: #2

- [ ] **[T-05 #5](https://github.com/Construct-Lab/reigner/issues/5)** `feat: agent loop` `L`
  - `harness/loop.py` + `harness/agent.py`: `Harness`, `Session`, `run_stream` (~300 lines)
  - Depends on: #3, #4
  - _Unblocks #6, #19, #22, #25, #28_

- [ ] **[T-06 #6](https://github.com/Construct-Lab/reigner/issues/6)** `feat: guardrails G1–G11` `L`
  - `truncation.py` (G2), `compaction.py` (G5/G10), `nudges.py` (G3/G4), `cache.py` (G9), `parallel.py` (G11), `oracle.py`
  - Depends on: #5

- [ ] **[T-48 #48](https://github.com/Construct-Lab/reigner/issues/48)** `feat: real-time steering interrupt` `M`
  - Make `mode="interrupt"` actually preempt the in-flight `adapter.call` (currently identical to `queue` at the loop layer)
  - Needs streaming adapters (Anthropic first) + cancellation plumbing in `run_loop`; tool batches already dispatched are allowed to finish
  - Depends on: #4, #5
  - _Future enhancement — surfaced during T-19 review; SPEC §5.6 / §22 Week 7 scope_

- [ ] **[T-64 #64](https://github.com/Construct-Lab/reigner/issues/64)** `fix: auto-register pseudo + provenance tools in Harness` `S`
  - `Harness.from_config` currently only registers artifact/search/custom tools; pseudo (`save_note`, `request_clarification`, `escalate_to_oracle`, `stop`) and `register_citation` never reach the registry, so the model can't see them
  - SPEC §6.4 mandates "always available unless explicitly disabled"; registry profile filtering on `s.pseudo` (registry.py:98,103) is dead code until this lands
  - Open: config knob for disabling; gate `escalate_to_oracle` on `cfg.oracle is not None`
  - Depends on: #5, #7, #8, #12
  - _Surfaced while reading T-12; blocks any end-to-end use of citations or scratchpad_

---

### Track B — Tool System

- [ ] **[T-07 #7](https://github.com/Construct-Lab/reigner/issues/7)** `feat: @tool decorator + ToolRegistry` `M`
  - `tools/base.py` + `tools/registry.py`: decorator, `ToolSpec`, `ToolResult`, profile filtering
  - Depends on: #1
  - _Unblocks #8, #9, #10, #11, #12_

- [ ] **[T-08 #8](https://github.com/Construct-Lab/reigner/issues/8)** `feat: pseudo-tools` `S`
  - `tools/pseudo/`: `save_note`, `request_clarification`, `escalate_to_oracle`, `stop`
  - Depends on: #7

- [ ] **[T-09 #9](https://github.com/Construct-Lab/reigner/issues/9)** `feat: artifact tools + ArtifactStore` `M`
  - `tools/artifacts/`: `ArtifactStore`, `read_artifact_file`, `grep_artifact`, `get_json_field`, `list_*`
  - Depends on: #7
  - Coordinate with: #13 (agree on `ArtifactSchema` interface before writing)

- [ ] **[T-10 #10](https://github.com/Construct-Lab/reigner/issues/10)** `feat: BM25 search tools` `M`
  - `tools/search/`: `SearchIndex` protocol, BM25 implementation, `bm25_search`, `filtered_search`, `section_search`
  - Depends on: #7

- [ ] **[T-11 #11](https://github.com/Construct-Lab/reigner/issues/11)** `feat: FS tools` `S`
  - `tools/fs/`: `fs_read`, `fs_grep`, `fs_glob`, `fs_ls`, optional `fs_write`
  - Depends on: #7

- [ ] **[T-12 #12](https://github.com/Construct-Lab/reigner/issues/12)** `feat: provenance and citations` `S`
  - `tools/provenance/`: `register_citation`, `get_citations`, lineage
  - Depends on: #7

---

### Track C — Artifact & Ingestion System

- [ ] **[T-13 #13](https://github.com/Construct-Lab/reigner/issues/13)** `feat: ArtifactSchema + ArtifactWriter` `M`
  - `artifacts/`: `ArtifactSchema`, `SectionSpec`, `JsonArtifactSpec`, `ArtifactWriter`, conventions, manifest
  - Depends on: #1
  - Coordinate with: #9 (agree on schema interface before either is merged)
  - _Unblocks #14, #16_

- [ ] **[T-14 #14](https://github.com/Construct-Lab/reigner/issues/14)** `feat: LLMExtractor base class` `L`
  - `ingestion/extractor.py` + `ingestion/results.py`: retry, validation, idempotency, cost tracking, `preprocess_pdf`
  - Depends on: #4, #13

- [ ] **[T-15 #15](https://github.com/Construct-Lab/reigner/issues/15)** `feat: document loaders` `S`
  - `ingestion/loaders/`: `PdfLoader`, `MdLoader`, `JsonLoader`, `UrlLoader`
  - Depends on: #1

- [ ] **[T-16 #16](https://github.com/Construct-Lab/reigner/issues/16)** `feat: IngestionPipeline` `M`
  - `ingestion/pipeline.py` + `ingestion/writers/`: concurrency, progress, dead-letter, idempotency, final report
  - Depends on: #13, #14, #15

---

### Track D — Config, CLI & Server

- [ ] **[T-17 #17](https://github.com/Construct-Lab/reigner/issues/17)** `feat: shared types + config schema` `M`
  - `types.py` + `config.py`: `reigner.yaml` Pydantic schema, loading, validation, all settings
  - Depends on: #1
  - _Unblocks #18 and all subsequent CLI tasks_

- [ ] **[T-18 #18](https://github.com/Construct-Lab/reigner/issues/18)** `feat: CLI skeleton + init command` `M`
  - `cli/__main__.py` + `cli/init.py`: entry point, `reigner init <name>` with three modes per SPEC §14:
    - `--guided` (default): interactive Q&A → LLM-generated REIGNER.md + schema.yaml, with confirmation gate before scaffolding `extractors/my_extractor.py`
    - `--recipe <name>`: verbatim copy of recipe scaffolds (no LLM call)
    - `--blank`: empty stubs only (offline)
  - Scaffolds the project layout from SPEC §9.1 (REIGNER.md, reigner.yaml, schema.yaml, extractors/, library/{raw,artifacts}/, search-index/, eval/, .env.example, .gitignore, README.md)
  - Depends on: #17

- [ ] **[T-19 #19](https://github.com/Construct-Lab/reigner/issues/19)** `feat: CLI chat REPL` `M`
  - `cli/chat.py`: interactive REPL with interrupt/queue steering; `--print` and `--json` modes
  - Depends on: #5, #18

- [ ] **[T-20 #20](https://github.com/Construct-Lab/reigner/issues/20)** `feat: CLI ingest + inspect commands` `S`
  - `cli/ingest.py` + `cli/inspect.py`: `reigner ingest`, `reigner inspect [artifacts|index|role|tools|session]`
  - Depends on: #16, #18

- [ ] **[T-21 #21](https://github.com/Construct-Lab/reigner/issues/21)** `feat: CLI session + eval commands` `S`
  - `cli/session.py` + `cli/eval.py`: session management commands, eval scorecard output
  - Depends on: #18, #25, #28

- [ ] **[T-22 #22](https://github.com/Construct-Lab/reigner/issues/22)** `feat: HTTP server` `M`
  - `server/fastapi_app.py`: `POST /run` (SSE streaming), `GET /health`
  - Depends on: #5, #17

- [ ] **[T-23 #23](https://github.com/Construct-Lab/reigner/issues/23)** `feat: MCP server export` `M`
  - `server/mcp_export.py`: expose all `@tool`-decorated functions as MCP-callable tools
  - Depends on: #7, #22

---

### Track E — Sessions, Eval & Plugins

- [ ] **[T-24 #24](https://github.com/Construct-Lab/reigner/issues/24)** `feat: session store` `M`
  - `sessions/store.py`: JSONL on-disk format, `save`/`load`/`export`/`import`, `meta.json`
  - Depends on: #2
  - _Unblocks #25_

- [ ] **[T-25 #25](https://github.com/Construct-Lab/reigner/issues/25)** `feat: session fork + replay + tree` `M`
  - `sessions/tree.py` + `sessions/replay.py`: branching, fork-tree navigation, deterministic replay
  - Depends on: #5, #24

- [ ] **[T-26 #26](https://github.com/Construct-Lab/reigner/issues/26)** `feat: plugin system` `M`
  - `plugins/`: `Plugin` protocol, all hook definitions, dotted-path registry loader
  - Depends on: #5

- [ ] **[T-27 #27](https://github.com/Construct-Lab/reigner/issues/27)** `feat: bundled plugins` `S`
  - `audit`, `metrics` (OpenTelemetry), `pii_redact`, `rate_limit`
  - Depends on: #26

- [ ] **[T-28 #28](https://github.com/Construct-Lab/reigner/issues/28)** `feat: eval suite + runner` `M`
  - `eval/runner.py` + `eval/cases.py`: `EvalSuite`, `EvalCase`, YAML-loadable cases
  - Depends on: #5, #24

- [ ] **[T-29 #29](https://github.com/Construct-Lab/reigner/issues/29)** `feat: eval checks` `M`
  - `faithfulness`, `repeated_calls`, `entity_resolution`, `coverage`, `latency_cost`
  - Depends on: #12, #28

---

## Phase 2 — Wire It Together

All Phase 1 tracks must be stable before these begin.

- [ ] **[T-30 #30](https://github.com/Construct-Lab/reigner/issues/30)** `feat: REIGNER.md loader + skill composition` `S`
  - `role/loader.py`: read `./REIGNER.md` from the project root (single file, no cascade per SPEC §9)
  - `role/compose.py`: append active skill blocks + dynamic per-turn context to the prompt
  - `role/templates/`: starter REIGNER.md files bundled with each recipe (init-time scaffolds, not runtime sources)
  - Sized down from M → S now that the cascade is gone
  - Depends on: #17

- [ ] **[T-31 #31](https://github.com/Construct-Lab/reigner/issues/31)** `feat: Skills system + 5 bundled skills` `M`
  - `skills/`: `Skill` protocol, `SkillRegistry`, `citation_strict`, `clarify_when_ambiguous`,
    `targeted_retrieval`, `chart_intent`, `scratchpad_discipline`
  - Depends on: #30

- [ ] **[T-32 #32](https://github.com/Construct-Lab/reigner/issues/32)** `feat: document_qa recipe` `L`
  - `recipes/document_qa/`: bundled REIGNER.md, reigner.yaml, schema.yaml, extractor stub (init-time scaffolds); `recipe.py` wires store, BM25, pseudo-tools, skills into a three-line API
  - Depends on: #8, #9, #10, #31
  - _The integration milestone — if this works end-to-end, the design is sound_

- [ ] **[T-33 #33](https://github.com/Construct-Lab/reigner/issues/33)** `feat: code_navigator recipe` `M`
  - `recipes/code_navigator/`: bundled REIGNER.md (exploration-oriented), FS tools, no schema
  - Depends on: #11, #30

- [ ] **[T-34 #34](https://github.com/Construct-Lab/reigner/issues/34)** `feat: SEC 10-K example` `L`
  - `examples/sec_10k/`: extractor, ingestion script, 20 eval cases, README
  - Validates SPEC.md §21 acceptance criteria end-to-end
  - Depends on: #16, #28, #32

---

## Dependency Map

```
#1 (setup)
├── #2 (events) ──────────────── #3 (state) ──┐
│                                 #4 (adapters) ├── #5 (loop) ── #6 (guardrails)
│                                              ┘              └── #48 (steering interrupt) ← needs #4 streaming
├── #7 (@tool) ── #8  (pseudo-tools)
│              ── #9  (artifact tools)   ← coordinate interface with #13
│              ── #10 (BM25)
│              ── #11 (FS tools)
│              ── #12 (provenance)
│
├── #13 (schema + writer) ── #14 (LLMExtractor)
│                         ── #16 (pipeline) ← also needs #15 (loaders)
│   #15 (loaders) ────────────────────────┘
│
├── #17 (config) ── #18 (CLI init) ── #19 (chat REPL)     ← needs #5
│                                  ── #20 (ingest+inspect) ← needs #16
│                                  ── #21 (session+eval)   ← needs #25, #28
│               ── #22 (HTTP) ── #23 (MCP export)
│
└── #2 (events) ── #24 (session store) ── #25 (fork+replay) ← needs #5
                ── #26 (plugins) ── #27 (bundled plugins)
                ── #28 (eval runner) ── #29 (eval checks) ← needs #12
```

---

## Labels

| Label | Purpose |
|---|---|
| `area:harness` | Track A |
| `area:tools` | Track B |
| `area:ingestion` | Track C |
| `area:cli` | Track D |
| `area:sessions` | Track E |
| `area:recipes` | Phase 2 |
| `blocked` | Waiting on another issue to merge |
| `size:S` | Hours |
| `size:M` | 1–2 days |
| `size:L` | 3+ days |

## Milestones

| Milestone | Issues | Goal |
|---|---|---|
| M1 — Foundations | #1–#4, #7, #13, #17 | Package boots; events, adapters, tool decorator, schema all exist |
| M2 — Working parts | #5–#29 | Every component functional and tested in isolation |
| M3 — Shipped | #30–#34 | `document_qa` works end-to-end; SEC example passes eval |
