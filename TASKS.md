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
  - `ingestion/extractor.py` + `ingestion/results.py`: retry, validation, idempotency, cost tracking, `raw_to_text`
  - Depends on: #4, #13

- [ ] **[T-15 #15](https://github.com/Construct-Lab/reigner/issues/15)** `feat: document loaders` `S`
  - `ingestion/loaders/`: `PdfLoader`, `MdLoader`, `JsonLoader`, `UrlLoader`
  - Depends on: #1

- [x] **[T-117 #117](https://github.com/Construct-Lab/reigner/issues/117)** `feat: HtmlLoader for HTML document ingestion` `S`
  - `ingestion/loaders/html.py`: bytes-only `HtmlLoader` owning `.html`/`.htm`, mirrors `PdfLoader` (tag-stripping stays the extractor's job); register + re-export
  - Depends on: #1
  - _Unblocks #34 (SEC 10-K example — filings are served as HTML); no `.html`/`.htm` loader exists today_

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

- [ ] **[T-73 #73](https://github.com/Construct-Lab/reigner/issues/73)** `feat: implement reigner init --guided` `M`
  - `cli/init.py`: wire the SPEC §14 default mode — interactive Q&A → model-generated REIGNER.md + schema.yaml, confirmation gate before scaffolding `extractors/my_extractor.py`, graceful no-API-key fallback to `--blank`
  - Make bare `reigner init <name>` adopt `--guided` as its default; remove the `_NO_MODE` / `_STUB_GUIDED` stub messages
  - Depends on: #4, #13, #17
  - _T-18 shipped only the `--blank` path and closed with `--guided` stubbed; this tracks the remaining default-mode work_

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

- [ ] **[T-23 #23](https://github.com/Construct-Lab/reigner/issues/23)** `feat: MCP export — serve the composed agent as one MCP tool` `M` `(v1)`
  - `server/mcp_export.py`: expose the composed agent as a single `ask_<project>` MCP tool over `harness.run`, not the individual `@tool` primitives
  - Depends on: #22

- [ ] **[T-74 #74](https://github.com/Construct-Lab/reigner/issues/74)** `feat: auto-load project .env at CLI startup` `S`
  - `cli/_env.py`: `load_project_env(config_path)` — `load_dotenv(root/".env", override=False)` from the resolved project root (`--config` parent or CWD); real OS env wins, no walk-up past root
  - Add `python-dotenv>=1.0` runtime dep; call from `chat`, `ingest`, `serve`, `init --guided` before building any adapter
  - Depends on: #17
  - _Fixes: keys in a project `.env` were never read because nothing seeded `os.environ` (SDKs read env directly)_

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
  - `metrics` (OpenTelemetry spans, `otel` extra), `pii_redact` (regex redaction)
  - `audit` and `rate_limit` dropped: audit duplicates the session store + external sinks; rate_limit could only throttle domain tool calls, not model-adapter calls
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

- [x] **[T-30 #30](https://github.com/Construct-Lab/reigner/issues/30)** `feat: REIGNER.md loader + skill composition` `S`
  - `role/loader.py`: read `./REIGNER.md` from the project root (single file, no cascade per SPEC §9)
  - `role/compose.py`: append active skill blocks + dynamic per-turn context to the prompt
  - `role/templates/`: starter REIGNER.md files bundled with each recipe (init-time scaffolds, not runtime sources)
  - Sized down from M → S now that the cascade is gone
  - Depends on: #17
  - Done — merged in #113 (implemented together with T-31: loader + skills are one change)

- [x] **[T-31 #31](https://github.com/Construct-Lab/reigner/issues/31)** `feat: Skills system + 5 bundled skills` `M`
  - `skills/`: `Skill` protocol, `SkillRegistry`, `citation_strict`, `clarify_when_ambiguous`,
    `targeted_retrieval`, `scratchpad_discipline`
  - Depends on: #30
  - Done — merged in #113. `chart_intent` intentionally dropped (no renderer consumes a chart block; revisit as a declarative `ChartIntentEvent` when a surface exists)

- [ ] **[T-32 #32](https://github.com/Construct-Lab/reigner/issues/32)** `feat: document_qa recipe` `L`
  - `recipes/document_qa/`: bundled REIGNER.md, reigner.yaml (artifacts + BM25 + pseudo-tools + skills + oracle), schema.yaml, extractor stub — curated init-time scaffolds copied by `reigner init --recipe document_qa`; a recipe is data, not code (no runtime `build()`)
  - Depends on: #8, #9, #10, #31
  - _The integration milestone — if this works end-to-end, the design is sound_

- [ ] **[T-33 #33](https://github.com/Construct-Lab/reigner/issues/33)** `feat: code_navigator recipe (multi-repo)` `L`
  - Multi-root `FsTools`: `tools.fs` accepts `root` (single) **or** `roots` (name→dir map) exposed as one virtual tree; first path segment selects the root, validated per-root; `fs_grep`/`fs_glob` fan out across roots (scope by root name), `fs_ls("")` lists roots; `build_fs_tools` validates each root exists at startup. Extends the FsTools from #11.
  - `recipes/code_navigator/`: sidecar recipe (data, not code) — bundled REIGNER.md (cross-repo exploration), reigner.yaml (`tools.fs.roots` placeholders, `write_enabled: false`), README, .gitignore. No schema/extractors/library/search-index; lean init via `_RECIPE_SKIP`.
  - Docs: SPEC §6 FS tools + §18 reframed (multi-repo navigator, sidecar, read-only default with opt-in write); this entry + issue #33.
  - _Why: one agent conversing across several repos at once (e.g. backend + frontend) is the wedge a single-working-directory coding agent can't match._
  - Depends on: #11, #30

- [x] **[T-34 #34](https://github.com/Construct-Lab/reigner/issues/34)** `feat: SEC 10-K example` `L`
  - `examples/sec_10k/`: extractor, ingestion script, 20 eval cases, README
  - Validates SPEC.md §21 acceptance criteria end-to-end
  - Depends on: #16, #28, #32

---

## Documentation

Cross-cutting docs work — no hard code dependency on the tracks above; documents the whole surface.

- [ ] **[T-75 #75](https://github.com/Construct-Lab/reigner/issues/75)** `docs: docs/USAGE.md — end-to-end feature & usage guide` `M`
  - Single Markdown guide: quick start, feature status table (✅ shipped / 🟡 partial / ⏳ planned), walkthrough in user order (init → ingest → chat → session → eval → serve), config reference, known gaps
  - Status flags verified against real CLI behavior, not assumed from TASKS.md; written MkDocs-friendly (headings/relative links) so #76 can render it as-is
  - Coordinate with: all tracks

- [ ] **[T-76 #76](https://github.com/Construct-Lab/reigner/issues/76)** `docs: scaffold MkDocs Material site + GitHub Pages deploy` `S`
  - `mkdocs.yml` (Material), `mkdocstrings[python]` API reference, GitHub Pages deploy Action with `mike` versioning; resolve the `docs/` source-dir vs. generated-HTML collision
  - Coordinate with: #75 (provides content)

---

## Phase 3 — v1 (post-v0)

Roadmap work that lands after the v0 rollout. Surfaced from the discussion in
[#71](https://github.com/Construct-Lab/reigner/issues/71): multimodal ingestion so
the agent can compile scanned and image-bearing documents. Tracked under milestone
**M4 — v1**.

- [ ] **[T-86 #86](https://github.com/Construct-Lab/reigner/issues/86)** `feat: multimodal adapter surface (image/content-part inputs)` `M`
  - Extend `ModelAdapter` beyond text-in/text-out: carry image/content-part inputs so the harness and `LLMExtractor.call_model` can send images alongside text (content-parts on `call` vs. a parallel `call_with_attachments` path is open)
  - Provider-neutral image part mapped to OpenAI image parts / Anthropic image blocks / Gemini `inline_data`; text-only callers unchanged
  - Depends on: #4
  - _Surfaced in #71; prerequisite for #87. SPEC section 5.3 / T-04 gap — no existing task covers it_

- [ ] **[T-87 #87](https://github.com/Construct-Lab/reigner/issues/87)** `feat: multimodal extraction for scanned & image documents` `M`
  - `LLMExtractor` passes page images straight to a vision model via #86 — vision reads scanned pages natively, so **no OCR** and **no `ImageLoader`** (a scanned PDF is still a PDF; the loader was never the missing piece)
  - PyMuPDF renders page pixmaps (no new heavy dep); `ExtractionResult` contract unchanged, so validation/retry/idempotency/cost all keep working
  - Reframe SPEC section 8.5: OCR superseded by multimodal extraction, not merely deferred
  - Depends on: #86, #13, #14
  - _Surfaced in #71; answers "ingest scanned PDFs?" (yes, via vision) and "need an ImageLoader?" (no)_

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
| `v1` | Post-v0 (v1) roadmap work — Phase 3 |
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
| M4 — v1 | #86, #87 | Multimodal ingestion: scanned/image documents via vision-capable adapter |
