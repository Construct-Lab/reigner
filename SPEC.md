# Reigner — v0 Specification

> A Python toolkit for building specialist agents over your own knowledge.
> Bring your `REIGNER.md`, your ingestion, and your domain tools.
> Reigner brings the loop that doesn't lose its mind, the retrieval that doesn't blow up your context, the sessions you can fork, and the citations that survive into the final answer.

**Status:** Draft v0 — single source of truth for the package design.
**Target language:** Python 3.12+
**Default install:** `pip install reigner` (also `uv add reigner`)
**License (planned):** Apache-2.0

---

## 1. What Reigner is, and what it isn't

### Is

A Python library for building **single-agent, retrieval-shaped, citation-faithful** agents over a developer's own corpus. Reigner ships:

- A disciplined agent loop with eleven baked-in guardrails for context economics, tool feedback, and graceful failure.
- A bounded, schema-aware retrieval tool surface (`read_artifact_file`, `grep_artifact`, `get_json_field`) plus a 50-line BM25 index.
- A typed streaming event protocol any UI can drive from.
- Forkable on-disk sessions you can replay and branch.
- A project-local `REIGNER.md` instruction file scaffolded at init time, with on-demand skill blocks composed in at runtime.
- One opinionated recipe (`document_qa`) that wires everything together for the ApolloScope-shaped use case, plus a contrast recipe (`code_navigator`) for raw filesystem access.
- A CLI with `init`, `ingest`, `chat`, `eval`, `inspect`, `serve`.
- An MCP server export so any Reigner tool is also an MCP-callable tool.

### Isn't

- Not a multi-agent orchestrator. One agent. If you need handoffs, you build them.
- Not a sandbox or runtime. Use Flue, Daytona, or E2B if your agents need to take actions in the world.
- Not a coding agent. Claude Code, Codex CLI, and Amp are excellent at that; Reigner is for question-answering over compiled knowledge.
- Not a hosted product. Open-source library only.
- Not a built-in vector store. The search interface is pluggable; vector backends are contributable.
- Not an LLM extractor library. Domain-specific extraction logic stays in user code.

---

## 2. Design principles

These are non-negotiable. Every module is judged against them.

1. **Opinionated core, extensible edges.** The loop and its eleven guardrails are baked in. Tools, schemas, ROLE, ingestion, and orchestration tweaks are pluggable.
2. **Bounded outputs as a discipline.** Every tool result is paginated, capped, and self-describing (`has_more`, `truncated`, `available_keys`, `missing_keys`). Tools that can't promise this don't ship in the default surface.
3. **Read-mostly by default.** Writes go through ingestion contracts, never agent tools. The corpus is *compiled*, not *navigated*.
4. **Citations are first-class.** Every numeric or factual claim flows through a `citation` event tied to a source artifact and locator. Faithfulness is checkable, not just asserted.
5. **Single agent, plural sessions.** One loop, one ROLE, one tool registry per Harness. Sessions are durable, forkable, branchable on disk.
6. **Convention by default, override when needed.** Defaults reflect what worked in production (the ApolloScope artifact layout, the H1–H11 settings). Every default is explicit and overridable.
7. **MCP as export, not entry.** Python-native tools are the front door; MCP servers are a renderer over the same tool definitions.
8. **The CLI is utility, not the product.** Reigner is a library first. The CLI exists to scaffold, run, and inspect.

---

## 3. Package layout

```
reigner/
├── __init__.py                  # public API: Harness, Session, tool, Skill, Plugin
├── harness/                     # opinionated core — the loop and its guarantees
│   ├── agent.py                 # Harness, Session
│   ├── loop.py                  # async streaming tool-call loop (G1-G11)
│   ├── events.py                # typed event dataclasses
│   ├── state.py                 # AgentState: history, scratchpad, cache, budgets
│   ├── truncation.py            # G2 — per-tool, JSON-aware result truncation
│   ├── compaction.py            # G5, G10 — history + progressive context compaction
│   ├── nudges.py                # G3, G4 — iteration and consecutive-error nudges
│   ├── cache.py                 # G9 — tool result cache
│   ├── parallel.py              # G11 — read-tool parallelization
│   ├── oracle.py                # escalation to a stronger model for one turn
│   └── adapters/                # model providers
│       ├── base.py              # ModelAdapter protocol
│       ├── openai.py
│       ├── anthropic.py
│       └── gemini.py
├── tools/                       # toolbox — pick what you need
│   ├── base.py                  # @tool decorator, ToolSpec, ToolResult
│   ├── registry.py              # ToolRegistry, schema generation, profiles
│   ├── pseudo/                  # locally-intercepted tools
│   │   ├── save_note.py
│   │   ├── request_clarification.py
│   │   ├── escalate_to_oracle.py
│   │   └── stop.py
│   ├── artifacts/               # schema-aware, bounded, read-mostly (default front door)
│   │   ├── store.py             # ArtifactStore
│   │   ├── read.py              # read_artifact_file
│   │   ├── grep.py              # grep_artifact
│   │   ├── json_field.py        # get_json_field
│   │   ├── list.py              # list_documents, list_versions, get_section
│   │   └── extensions.py        # supported file types for grep/read
│   ├── fs/                      # raw filesystem — explicit opt-in, documented as risky
│   │   ├── read.py
│   │   ├── grep.py
│   │   ├── glob.py
│   │   ├── ls.py
│   │   └── write.py             # gated behind FsTools(write_enabled=True)
│   ├── search/                  # retrieval primitives
│   │   ├── bm25.py              # 50-line BM25 over JSON sidecar (default)
│   │   ├── base.py              # SearchIndex protocol — swap in vector/SQL
│   │   └── filters.py
│   └── provenance/
│       ├── citations.py         # register_citation, get_citations
│       └── lineage.py
├── artifacts/                   # ingestion-side conventions
│   ├── schema.py                # ArtifactSchema
│   ├── writer.py                # ArtifactWriter — atomic, idempotent
│   ├── conventions.py           # default layout: raw/, artifacts/{entity}/{version}/
│   └── manifest.py              # extraction_meta.json structure
├── ingestion/                   # optional helpers — domain code lives outside
│   ├── pipeline.py              # IngestionPipeline
│   ├── extractor.py             # LLMExtractor base class
│   ├── results.py               # ExtractionResult, ExtractionError, TransientError, ValidationError
│   ├── loaders/                 # PdfLoader, MdLoader, JsonLoader, UrlLoader
│   ├── writers/                 # ArtifactWriter, Bm25IndexWriter
│   └── transforms/              # base classes for non-LLM transforms
├── role/                        # REIGNER.md handling
│   ├── loader.py                # reads ./REIGNER.md from the project root
│   ├── compose.py               # per-turn dynamic context + skill block injection
│   └── templates/               # starter REIGNER.md files for each recipe (init-time scaffolds)
├── skills/                      # composable instruction modules — on-demand loaded
│   ├── base.py                  # Skill protocol
│   ├── registry.py              # SkillRegistry, on-demand activation
│   ├── citation_strict.py
│   ├── clarify_when_ambiguous.py
│   ├── targeted_retrieval.py
│   ├── chart_intent.py
│   └── scratchpad_discipline.py
├── recipes/                     # init-time scaffolds (§9, §14)
│   ├── document_qa/             # the v0 hero recipe (ApolloScope-shaped)
│   │   ├── __init__.py
│   │   ├── recipe.py
│   │   ├── REIGNER.md           # copied into the user's project at init
│   │   ├── reigner.yaml         # copied into the user's project at init
│   │   ├── schema.yaml          # copied into the user's project at init
│   │   └── extractor_stub.py    # copied to extractors/my_extractor.py at init
│   └── code_navigator/          # contrast recipe (Flue-shaped, opt-in)
│       └── ...
├── sessions/                    # forkable, branchable, durable
│   ├── store.py                 # SessionStore, on-disk JSONL format
│   ├── tree.py                  # branching, forking, tree navigation
│   └── replay.py                # deterministic replay with a stub adapter
├── plugins/                     # extension points
│   ├── base.py                  # Plugin protocol, hooks
│   ├── hooks.py                 # before_tool_call, after_tool_call, on_compaction, ...
│   └── registry.py
├── eval/
│   ├── runner.py                # reigner eval
│   ├── faithfulness.py
│   ├── repeated_calls.py
│   ├── entity_resolution.py
│   ├── coverage.py
│   └── cases.py
├── cli/
│   ├── __main__.py
│   ├── init.py
│   ├── ingest.py
│   ├── chat.py                  # interactive REPL with steering
│   ├── eval.py
│   ├── inspect.py
│   ├── session.py               # list, fork, replay, export, import
│   └── serve.py                 # FastAPI HTTP server / MCP server export
├── server/
│   ├── fastapi_app.py           # SSE streaming endpoint
│   └── mcp_export.py            # expose tools as MCP server
├── config.py                    # reigner.yaml schema, loading, validation
└── types.py                     # shared types
```

---

## 4. The public API at a glance

This is what a developer's `main.py` looks like. Everything below is in service of making this work.

```python
import asyncio
from reigner import Harness, tool
from reigner.tools.artifacts import ArtifactStore, ArtifactSchema
from reigner.tools.search import Bm25Index

# 1. Define your artifact schema
schema = ArtifactSchema(
    entity_path="{entity_id}/{year}",
    json_artifacts=["metadata.json", "metrics.json"],
    sections=["document_summary", "sections/*", "insights/*"],
)

store = ArtifactStore(root="library/artifacts", schema=schema)
index = Bm25Index(path="search-index/documents.json")

# 2. Add custom tools alongside built-ins
@tool(readonly=True, cache=True)
async def get_market_cap(ticker: str, year: int) -> dict:
    """Fetch market cap for a ticker in a given fiscal year."""
    ...

# 3. Build the harness
harness = Harness.from_config(
    "reigner.yaml",
    tools=[*store.tools(), *index.tools(), get_market_cap],
)

# 4. Run a session
async def main():
    session = harness.session(state={"user_id": "u1"})
    async for event in session.run_stream("What were Apple's R&D expenses in 2024?"):
        print(event)

asyncio.run(main())
```

The recipe path — same agent, three lines:

```python
from reigner.recipes import document_qa

harness = document_qa.build(artifacts_root="library/artifacts")
session = harness.session()
```

---

## 5. The Harness Core (`reigner.harness`)

This is the opinionated, non-negotiable part. Everything else can be swapped; this can't.

### 5.1 Public types

```python
class Harness:
    @classmethod
    def from_config(cls, path: str, tools: list[Tool] = None) -> "Harness": ...
    def session(
        self,
        state: dict = None,
        history: list = None,
        session_id: str = None,
        profile: str = "full",  # or "read_only", "eval"
    ) -> "Session": ...

class Session:
    id: str
    parent_id: str | None
    async def run_stream(self, query: str) -> AsyncIterator[Event]: ...
    async def run(self, query: str) -> FinalAnswer: ...
    def history(self) -> list[Turn]: ...
    def notes(self) -> list[Note]: ...
    def fork(self, at_turn: int = -1) -> "Session": ...
    async def steer(self, message: str, mode: Literal["interrupt", "queue"] = "interrupt"): ...
    def save(self) -> Path: ...
    @classmethod
    def load(cls, session_id: str) -> "Session": ...
```

`Session` is multi-turn and mutable. `Harness` is the immutable configured loop. State that varies per conversation (history, scratchpad, cache, budgets used) lives on `Session`. State that's shared across conversations (tools, ROLE, model, defaults) lives on `Harness`.

### 5.2 The event protocol

```python
@dataclass
class StatusEvent:        type = "status";        message: str
@dataclass
class ToolCallEvent:      type = "tool_call";     name: str; args: dict; call_id: str
@dataclass
class ToolResultEvent:    type = "tool_result";   call_id: str; result: Any; truncated: bool; cached: bool
@dataclass
class CitationEvent:      type = "citation";      source: str; locator: dict; value: Any
@dataclass
class ClarificationEvent: type = "clarification"; question: str; candidates: list
@dataclass
class FinalAnswerEvent:   type = "final_answer";  text: str; metadata: dict
@dataclass
class ErrorEvent:         type = "error";         error: str; recoverable: bool
@dataclass
class CompactionEvent:    type = "compaction";    level: int; tokens_freed: int
@dataclass
class OracleEscalationEvent: type = "oracle";    reason: str; from_model: str; to_model: str
@dataclass
class SteeringAcceptedEvent: type = "steering";  message: str; mode: str
```

Every UI driving Reigner consumes these events. CLI, web UI, IDE plugin, MCP transport — same protocol.

### 5.3 The loop

The loop is small on purpose (~300 lines fleshed out). A developer can read it end-to-end and understand what their agent is doing.

> **v1 follow-up (#86):** `adapter.call(prompt, tools)` is text-in / text-out in v0. v1 extends the adapter surface to carry image/content-part inputs (one path serving both the loop and `LLMExtractor.call_model`), enabling the multimodal extraction in section 8.5 (#87).

```python
async def run_loop(state: AgentState) -> AsyncIterator[Event]:
    while not state.done:
        # Refresh dynamic context (iters_remaining, now, answer_id, ...)
        state.refresh_context()

        # Steering: any messages enqueued since last iteration?
        if state.has_pending_steering():
            state.consume_steering()

        # Progressive compaction at 80/90/95%
        if pressure := state.context_pressure() > 0.8:
            yield await state.compact(pressure)

        # Build prompt with stable/dynamic boundary
        prompt = state.build_prompt()

        # Model call (or oracle if escalated)
        adapter = state.oracle_adapter or state.adapter
        action = await adapter.call(prompt, state.tools)

        # Iteration nudges
        if state.should_nudge():
            state.inject_nudge()

        # Final answer terminates
        if action.is_final_answer:
            yield FinalAnswerEvent(text=action.text, metadata=...)
            state.done = True
            break

        # Pseudo-tools intercepted locally
        if action.tool_name in PSEUDO_TOOLS:
            yield await handle_pseudo(state, action)
            continue

        # Parallel reads if all calls are readonly; else serial
        results = await execute_tools(action.tool_calls, state)

        for call, result in results:
            cached = state.cache.was_hit(call)
            truncated_result, was_truncated = state.truncate_for_tool(call.name, result)
            yield ToolResultEvent(
                call_id=call.id,
                result=truncated_result,
                truncated=was_truncated,
                cached=cached,
            )

        # Consecutive error detection
        if state.consecutive_errors() >= state.max_consecutive_errors:
            state.inject_early_stop_nudge()

        if state.iterations >= state.max_iterations:
            yield ErrorEvent(error="max_iterations", recoverable=False)
            break
```

### 5.4 The eleven guardrails

Renamed from H1–H11 (ApolloScope's "Harness" prefix) to G1–G11 (Guardrail). These are baked-in defaults a developer opts *out* of, not into.

| ID | Name | Module | Brief |
|---|---|---|---|
| G1 | Stable / dynamic prompt boundary | `state.build_prompt` | Caching-friendly: `STABLE: <role + tool schemas>` then `DYNAMIC: <history + state>`. |
| G2 | Per-tool truncation budgets | `truncation.truncate_for_tool` | JSON-boundary aware. Per-tool override of global cap. |
| G3 | Iteration nudges | `nudges.iteration_nudge` | Strategic nudges injected every N iterations. |
| G4 | Consecutive-error nudge | `nudges.error_nudge` | Forced early-stop nudge after 3 consecutive tool errors. |
| G5 | History compaction | `compaction.compact_history` | Last 3 turns full, older summarised. |
| G6 | Dynamic context per turn | `state.refresh_context` | Recomputes `iters_remaining`, `now()`, `answer_id`. |
| G7 | Tool-relevant context injection | `state.refresh_context` | Surfaces relevant prior notes/citations into the next turn. |
| G8 | Scratchpad survives compaction | `pseudo.save_note` | Notes accessible via `session.notes()`. |
| G9 | Tool result cache | `cache.ToolResultCache` | Keyed on `(tool_name, args_hash)`; per-session. |
| G10 | Progressive compaction | `compaction.progressive` | Tiers at 80/90/95% of budget. |
| G11 | Parallel read execution | `parallel.execute_reads` | `asyncio.gather` for `readonly=True` tools. |

### 5.5 Oracle escalation

A pseudo-tool the model can call:

```python
@pseudo_tool
def escalate_to_oracle(reason: str) -> dict:
    """Escalate the next turn to a more capable model.

    Use only when a question genuinely requires deeper reasoning than the
    current model has provided in the last 2-3 iterations. Cite the reason.
    """
```

Configured in `reigner.yaml`:

```yaml
oracle:
  provider: anthropic
  model: claude-opus-4-7
```

The next single turn uses the oracle adapter; subsequent turns revert. Emits `OracleEscalationEvent`. Costs are surfaced in session metadata.

### 5.6 Steering

`session.steer(message, mode)` enqueues a user message that's delivered at the next tool boundary:

- `mode="interrupt"`: delivered after the current tool call completes; remaining queued tool calls in this iteration are dropped.
- `mode="queue"`: delivered after the current iteration finishes naturally.

Enqueued steering messages persist on `Session.pending_steering` until consumed. Emits `SteeringAcceptedEvent` when consumed.

The CLI's `chat` REPL uses this: pressing Enter mid-run sends a `mode="interrupt"` message; pressing Alt+Enter queues it.

---

## 6. The Tool System (`reigner.tools`)

### 6.1 The `@tool` decorator

```python
@tool(
    readonly=True,           # eligible for G11 parallel exec and G9 caching
    cache=True,              # cache results within a session
    truncate_chars=8000,     # per-tool override of G2 budget
    description="...",       # surfaces in tool schema; defaults to docstring
    profile="full",          # which permission profile this tool belongs to
)
async def get_metric(entity_id: str, year: int, key: str) -> dict:
    """Fetch a typed metric for an entity in a year."""
    ...
```

Args auto-convert to JSON Schema for the model. Return values auto-serialize. Errors are caught and converted to `ErrorEvent` with the original exception preserved on `event.metadata.exception`.

### 6.2 Tool categories

| Category | Marker | Defaults |
|---|---|---|
| Read | `readonly=True` | Parallelizable, cacheable, retryable |
| Write | `readonly=False` | Serial only, never cached, explicit retry policy |
| Pseudo | `pseudo=True` | Intercepted locally, never reach external services |
| Domain | `@tool(...)` | Whatever the developer declares |

### 6.3 Permission profiles

A profile is a named tool subset. Sessions take a `profile` parameter that filters which tools are exposed.

| Profile | Includes | Use case |
|---|---|---|
| `full` | All registered tools | Default for production sessions |
| `read_only` | Only `readonly=True` tools (and pseudo-tools) | Plan/explore mode, eval, untrusted contexts |
| `eval` | `readonly=True` tools, no oracle, no clarification | Deterministic eval runs |

Profiles are configured per-tool in the decorator and switchable per-session.

### 6.4 Built-in tools

**Pseudo-tools** (always available unless explicitly disabled):

- `save_note(text)` — durable scratchpad (G8).
- `request_clarification(question, candidates)` — pause the loop, emit `ClarificationEvent`.
- `escalate_to_oracle(reason)` — single-turn model escalation.
- `stop(reason)` — graceful early termination.

**Artifact tools** (opt-in via `ArtifactStore`):

```python
@tool(readonly=True, profile="read_only")
async def read_artifact_file(path: str, offset: int = 0, limit: int = 4000) -> dict:
    """Read a chunk of a text artifact.

    Returns:
        {
          content: str,
          offset: int,
          limit: int,
          has_more: bool,
          total_size: int,
        }
    """

@tool(readonly=True, profile="read_only")
async def grep_artifact(
    pattern: str,
    file_path: str | None = None,
    extensions: list[str] | None = None,
) -> dict:
    """Plain-text search across artifact files.

    Returns:
        {
          matches: [
            {file_path: str, offset: int, line_number: int, line_preview: str},
            ...  # capped at 10
          ],
          truncated: bool,
          total_files_searched: int,
        }
    """

@tool(readonly=True, profile="read_only")
async def get_json_field(path: str, fields: list[str]) -> dict:
    """Extract specific top-level keys from a JSON artifact.

    Returns:
        {
          fields: {key: value, ...},
          available_keys: [str, ...],
          missing_keys: [str, ...],
        }
    """

@tool(readonly=True, profile="read_only")
async def list_documents(filters: dict = None) -> list[dict]: ...

@tool(readonly=True, profile="read_only")
async def get_section(entity_id: str, version: str, section: str) -> dict: ...

@tool(readonly=True, profile="read_only")
async def list_versions(entity_id: str) -> list[str]: ...
```

**Search tools** (opt-in via `Bm25Index`):

- `bm25_search(query, filters, top_k)`
- `filtered_search(filters, top_k)`
- `section_search(query, section_name, top_k)`

**FS tools** (opt-in via `FsTools`, documented as risky):

- `fs_read`, `fs_grep`, `fs_glob`, `fs_ls`, optionally `fs_write`.
- All bounded by config (max bytes, max lines, max matches), but explicit warning in docs that bounded ≠ self-describing the way artifact tools are.

Use cases devs reach for `FsTools` for:

- **Code navigator / repo Q&A** — agent answers "where is X defined", "what calls Y" over a live repo. The canonical case; `code_navigator` recipe.
- **Log / config investigator** — point at a log or config tree; agent triages incidents or explains drift. No compile step makes sense; contents change constantly.
- **Migration / refactor assistant** — `write_enabled=True`, scoped to a feature branch. Agent renames symbols, updates imports, rewrites configs.
- **Doc-site author** — agent reads markdown sources, writes new pages. Whole-file writes match the workflow.
- **Scratch / sandbox agents** — quick prototypes where building an artifact schema is overkill. Point at a `notes/` directory and ship.
- **Ingestion debugging** — run an agent over the raw, pre-ingestion corpus to figure out what the schema should be, then graduate to `ArtifactStore`.
- **Hybrid recipes with hard separation** — `ArtifactStore` for the grounded answer surface plus `FsTools` scoped to a read-only side directory (e.g. `examples/`) the agent can cite from without polluting the main corpus.
- **MCP export** — every `@tool` is MCP-clean, so `FsTools` becomes a sandboxed filesystem MCP server for external clients with no extra code.

`FsTools` and `ArtifactStore` are alternatives, not complements: a recipe picks one as the primary surface. Registering both in the same agent is supported but loses the grounding `ArtifactStore` exists to enforce — the model will reach for `fs_read` and bypass the schema. The "hybrid" case above works only because the two surfaces cover disjoint paths.

---

## 7. The Artifact System

Split into write-side and read-side because they have different audiences.

### 7.1 `ArtifactSchema` (declarative)

```python
@dataclass
class ArtifactSchema:
    entity_path: str = "{entity_id}/{version}"
    json_artifacts: list[str] = field(default_factory=lambda: ["metadata.json"])
    sections: list[str] = field(default_factory=lambda: ["document_summary", "sections/*"])
    raw_path: str = "raw/{entity_id}/{version}.{ext}"
    extraction_meta: str = "extraction_meta.json"
    text_extensions: set[str] = field(default_factory=lambda: {".csv", ".json", ".jsonl", ".md", ".txt", ".tsv", ".yaml", ".yml"})

    @classmethod
    def document_qa_default(cls) -> "ArtifactSchema": ...

    @classmethod
    def from_yaml(cls, path: str) -> "ArtifactSchema": ...
```

The schema is the contract. Both the artifact tools and the ingestion writer reference it. Developers declare a schema or use a default. **For extraction validation (§8), the schema's `SectionSpec` and `JsonArtifactSpec` types also declare field-level requirements that the `LLMExtractor` validates against.**

### 7.2 `ArtifactStore` (read-side)

```python
class ArtifactStore:
    def __init__(self, root: str, schema: ArtifactSchema): ...

    def tools(self) -> list[Tool]:
        """Return the bound tool surface."""
        return [
            self.list_documents,
            self.get_section,
            self.read_artifact_file,
            self.grep_artifact,
            self.get_json_field,
            self.list_versions,
        ]
```

### 7.3 `ArtifactWriter` (write-side, ingestion-only)

```python
writer = ArtifactWriter(root="library/artifacts", schema=schema)

writer.write_entity(
    entity_id="AAPL",
    version="2024",
    metadata={...},
    sections={"document_summary": "...", "sections/risks": "..."},
    json_artifacts={"metadata.json": {...}, "metrics.json": {...}},
)
```

Atomic (write-then-rename), idempotent (keyed on `(entity_id, version, schema_version)`), version-aware. Never exposed as an agent tool.

---

## 8. The Ingestion System

Three layers, with Reigner's involvement decreasing as you go up the stack. Layer A is Reigner's contract. Layer B is user code, scaffolded by Reigner. Layer C is Reigner's runner.

```
┌────────────────────────────────────────────────────────────────┐
│ Layer C — IngestionPipeline   (Reigner: runner)                │
│   concurrency, progress, errors, directory-level idempotency   │
├────────────────────────────────────────────────────────────────┤
│ Layer B — LLMExtractor        (user: prompt + preprocessing)   │
│                               (Reigner: adapters, retry,       │
│                                validation, cost, idempotency)  │
├────────────────────────────────────────────────────────────────┤
│ Layer A — ArtifactSchema      (Reigner: declarative contract)  │
│   declares the shape of compiled artifacts; see §7.1           │
└────────────────────────────────────────────────────────────────┘
```

### 8.1 Layer A — ArtifactSchema (declarative)

The shape of your compiled artifacts. Declared once. Validates extraction outputs. Tells artifact tools what to expect on disk.

The base `ArtifactSchema` from §7.1 is extended with field-level type info so extraction can be validated:

```python
from reigner.artifacts import ArtifactSchema, SectionSpec, JsonArtifactSpec

schema = ArtifactSchema(
    entity_path="{ticker}/{fiscal_year}",
    sections=[
        SectionSpec(name="document_summary", required=True, max_chars=2000),
        SectionSpec(name="sections/business", required=True),
        SectionSpec(name="sections/risk_factors", required=True),
        SectionSpec(name="insights/key_risks", required=False),
    ],
    json_artifacts=[
        JsonArtifactSpec(
            name="metadata.json",
            fields={
                "ticker": str,
                "fiscal_year": int,
                "filing_date": str,
                "company_name": str,
            },
        ),
        JsonArtifactSpec(
            name="metrics.json",
            fields={
                "revenue": float,
                "net_income": float,
                "research_and_development": float,
                "total_assets": float,
            },
        ),
    ],
)
```

The schema can also be authored as YAML and loaded via `ArtifactSchema.from_yaml(path)`.

### 8.2 Layer B — LLMExtractor (user code, Reigner-scaffolded)

Where domain knowledge lives. The user writes a subclass of `LLMExtractor` that contains the prompt and any preprocessing. Reigner provides everything around it.

```python
from reigner.ingestion import LLMExtractor, ExtractionResult

class TenKExtractor(LLMExtractor):
    schema = schema                  # the ArtifactSchema from §8.1
    model = "gemini-2.0-pro"          # or "anthropic:claude-...", "openai:gpt-..."
    max_retries = 2

    PROMPT = """
    You are reading a SEC 10-K annual filing for {company_name} ({ticker})
    for fiscal year {fiscal_year}.

    Extract the following into structured JSON matching the provided schema.
    If a value cannot be found, return null. Do not estimate.

    Schema:
    {schema_as_json_schema}
    """

    async def extract(self, raw: bytes, meta: dict) -> ExtractionResult:
        text = await self.preprocess_pdf(raw)
        response = await self.call_model(
            prompt=self.PROMPT.format(
                **meta,
                schema_as_json_schema=self.schema.to_json_schema(),
            ),
            input_text=text,
            response_format="json",
        )
        return ExtractionResult(
            sections={
                "document_summary": response["document_summary"],
                "sections/business": response["business"],
                "sections/risk_factors": response["risk_factors"],
            },
            json_artifacts={
                "metadata.json": {
                    "ticker": meta["ticker"],
                    "fiscal_year": meta["fiscal_year"],
                    "filing_date": meta["filing_date"],
                    "company_name": meta["company_name"],
                },
                "metrics.json": response["metrics"],
            },
        )
```

**What Reigner provides via `LLMExtractor`:**

- `self.call_model(prompt, input_text, response_format)` — same model adapters as the harness; the user never writes provider-specific code.
- Retry with exponential backoff on transient errors (rate limits, 5xx).
- Schema validation of the returned JSON against `self.schema` — required sections and required JSON fields are checked; missing required fields raise `ExtractionError` with a clear message rather than producing a malformed artifact.
- Token and cost tracking per extraction, surfaced in pipeline metrics.
- Idempotency keyed on `(source_hash, schema_version, prompt_hash)`. If the prompt changes, re-extraction happens automatically; if it doesn't, the cached extraction is reused.
- Standard error patterns: `TransientError` (retried), `ExtractionError` (routed to dead-letter), `ValidationError` (routed to dead-letter with the malformed payload preserved).
- A default `preprocess_pdf` implementation using `pymupdf`; override for domain-specific PDF handling (multi-column layouts, tables, scanned pages, etc.). PyMuPDF is AGPL-3.0; downstream users requiring a permissive license can install `pymupdf-pro` or override `preprocess_pdf` with another loader.

> **v1 follow-up (#87):** `preprocess_pdf` is text-only, so scanned PDFs fail in v0. v1 adds a multimodal extraction path — page images sent straight to a vision model via the multimodal adapter (#86) — so scanned and image-bearing documents need no OCR. See section 8.5.

**What the user provides:**

- `PROMPT` — the actual instructions. Irreducibly domain-specific.
- `extract()` — the orchestration of preprocess → prompt → parse → return.
- Optionally, an override of `preprocess_pdf` or any other preprocessing.

**What Reigner deliberately does not ship:**

Pre-built extractors for any specific domain. A 10-K extractor, a research paper extractor, a medical guideline extractor, and a legal contract extractor all need fundamentally different prompts and preprocessing. Shipping one would be lying about Reigner's scope. The `LLMExtractor` base class makes writing one cheap (typically ~50 lines including the prompt).

The example in `examples/sec_10k/extractor.py` shows a complete real-world extractor as documentation-by-demonstration, not as a supported component.

### 8.3 Layer C — IngestionPipeline (runner)

The pipeline glues loaders, extractors, and writers together.

```python
from reigner.ingestion import IngestionPipeline
from reigner.ingestion.loaders import PdfLoader
from reigner.ingestion.writers import ArtifactWriter, Bm25IndexWriter

pipeline = IngestionPipeline(
    loaders=[PdfLoader(meta_extractor=parse_filing_metadata)],
    transforms=[TenKExtractor()],
    writers=[
        ArtifactWriter(root="library/artifacts", schema=schema),
        Bm25IndexWriter(path="search-index/documents.json"),
    ],
    concurrency=4,
    on_error="dead_letter",   # or "raise", "skip"
    dead_letter_path="library/_dead_letter/",
)

await pipeline.run("data/raw/10k/")
```

The pipeline handles:

- Concurrency across documents (configurable; default 4).
- Progress reporting via the same event protocol as the agent loop.
- Idempotency at the directory level: previously-ingested documents matching the current `(source_hash, schema_version, prompt_hash)` key are skipped.
- Error routing per the `on_error` policy: `raise` (default for development), `dead_letter` (default for production), or `skip`.
- Final report: count successful, count failed, total tokens, total cost, total wall-clock time.

### 8.4 What ships with Reigner

- `IngestionPipeline` (the runner).
- `LLMExtractor` base class with all scaffolding described in §8.2.
- Loaders: `PdfLoader`, `MdLoader`, `JsonLoader`, `UrlLoader`.
- Writers: `ArtifactWriter`, `Bm25IndexWriter`.
- Transform base classes for non-LLM transforms (e.g. deterministic parsers, format converters).

### 8.5 What does not ship with Reigner

- Specific extractors for any domain.
- Specific PDF parsing strategies beyond a basic default.
- An OCR pipeline. **v1 supersedes this rather than deferring it** (#87): scanned and image-bearing documents are handled by *multimodal extraction* — `LLMExtractor` passes page images straight to a vision model via the multimodal adapter (#86) — so OCR is unnecessary, not just out of scope. For v0, run a separate library (`unstructured` / `marker`) upstream if needed. Note there is deliberately **no `ImageLoader`**: a scanned PDF is still a PDF, so the loader was never the missing piece.
- A document deduplication layer (idempotency is per-source, not cross-source).

---

## 9. The instruction file (`REIGNER.md`)

Every Reigner project has one instruction file at its repo root: `./REIGNER.md`. This file is the single runtime source of truth for what the agent is, what it does, and how it behaves. The name follows the AGENTS.md / CLAUDE.md / CURSOR.md convention: discoverable, tool-specific, version-controlled alongside the rest of the user's project.

Reigner deliberately **rejects a runtime cascade** across machine-global, project, and recipe layers. The reasoning:

- **Reigner is a toolbox for shipping per-project agents.** Users build agents to open-source or to ship to clients. Runtime behavior must be reproducible from the contents of the project repo. A machine-global `~/.reigner/REIGNER.md` silently shaping a deployed agent's behavior — present on the dev's laptop, absent in production — is exactly the footgun this design rejects.
- **Recipes are init-time scaffolds, not runtime sources.** When the user runs `reigner init <name> --recipe document_qa`, the recipe's bundled `REIGNER.md` is *copied into the project verbatim*. After init, the recipe is no longer referenced; the project owns its REIGNER.md. There is no merge, no cascade, no implicit override.
- **Skills are the only on-demand layer.** Skill instructions (§10) are appended to the prompt when the model invokes the skill. Skills live in the package; they are dynamic by nature because the model is choosing them mid-loop.

The instruction file uses `## ` headers to delimit sections (identity, retrieval grammar, citation rules, etc.). Sections are model-readable prose plus optional YAML front-matter for metadata.

```yaml
# reigner.yaml
role:
  file: REIGNER.md           # project-relative; defaults to ./REIGNER.md
  skills:
    - citation_strict
    - targeted_retrieval
```

The composed prompt (REIGNER.md + active skill blocks + dynamic per-turn context) is logged once per session and visible via `reigner inspect role`. Opaque instruction sets are the #1 source of "why is my agent doing this?" debugging pain — keeping the source on disk, single-file, and inspectable solves that directly.

### 9.1 What `reigner init` produces

`reigner init <name>` is the make-or-break DX moment (see §14 for the three init modes). Every mode produces the same project layout:

```
my_app/
├── REIGNER.md              # the instruction file — generated, copied, or stubbed
├── reigner.yaml            # config: model, settings, paths
├── schema.yaml             # ArtifactSchema declaration
├── extractors/             # user's LLMExtractor subclasses (Layer B per §8.2)
│   ├── __init__.py
│   └── my_extractor.py     # commented stub showing the LLMExtractor pattern
├── library/
│   ├── raw/                # user drops source documents here
│   └── artifacts/          # populated by `reigner ingest`
├── search-index/           # BM25 sidecar lands here
├── eval/
│   └── cases.yaml          # one starter case + comments
├── .env.example            # ANTHROPIC_API_KEY=... etc
├── .gitignore              # ignores library/artifacts, search-index, .env, .reigner/
└── README.md               # how to ingest, chat, eval
```

Compiled artifacts, the search index, and session state are **derived data** and excluded from version control by the scaffolded `.gitignore`. The user's source-of-truth files — `REIGNER.md`, `reigner.yaml`, `schema.yaml`, `extractors/`, `library/raw/` — are committed.

---

## 10. Skills (`reigner.skills`)

Skills are **on-demand-loaded instruction modules**. The model sees a list of skill names and one-line descriptions in the ROLE; full instructions and tools load only when the model invokes the skill.

This is Pi's pattern, adapted. It keeps the system prompt small and improves prompt-cache hit rates.

```python
from reigner.skills import Skill

class CitationStrict(Skill):
    name = "citation_strict"
    description = "Refuse to make numeric claims without a registered citation."
    tools_required: list[str] = []  # validate at recipe build

    instructions = """
    When asserting a numeric value, you must:
    1. Have retrieved it from an artifact in this session.
    2. Register the citation via the citation hook.
    3. Reference the source in the answer text.
    If you cannot satisfy these, say "I don't have a verifiable source for that"
    and offer to search or escalate.
    """

    examples = [...]
```

Bundled skills in v0:

- `citation_strict`
- `clarify_when_ambiguous`
- `targeted_retrieval` (the `get_json_field → grep → read` grammar)
- `chart_intent` (emit `<chart_intent>` blocks before final answer)
- `scratchpad_discipline` (when to use `save_note`)

Skills declared in `reigner.yaml`:

```yaml
role:
  skills:
    - citation_strict
    - targeted_retrieval
```

Naming note: these are *Reigner skills*, not Claude's "Skills" feature. Different concept; same word; documented to avoid confusion.

---

## 11. Sessions (`reigner.sessions`)

Sessions are **durable, forkable, branchable JSON files on disk**. Inspired by Pi.

### 11.1 Storage

- Location: `./.reigner/sessions/` inside the user's project (configurable). Project-local by default — same reasoning as §9: runtime state belongs to the project, not the machine. The `.gitignore` scaffolded by `reigner init` excludes this directory.
- One file per session: `{session_id}.jsonl`.
- One JSON line per event in the protocol.
- Optional `meta.json` per session: title, parent_id, created, last_updated, total tokens, total cost.

### 11.2 Operations

```python
session = harness.session(session_id="abc123")
session.fork(at_turn=5)         # branch from turn 5; new session_id, parent_id="abc123"
session.replay(at_turn=3)       # rerun from turn 3 against current model & ROLE
session.save()                  # explicit save; auto-saves after each event by default
Session.load(session_id="abc123")
Session.export(session_id, path="./session.jsonl")
Session.import_(path)
```

CLI:

```
reigner session list
reigner session fork <id> [--at-turn N]
reigner session replay <id> [--at-turn N] [--with-role ./REIGNER.md]
reigner session export <id> --to <path>
reigner session import <path>
reigner session tree <id>      # show fork tree
```

### 11.3 Why this matters for Reigner specifically

Retrieval agents are debugged by re-running the same query against ROLE variants, tool variants, or model variants. Without forkable sessions, every iteration is a new conversation; with them, you compare A/B/C against the same starting point. This is one of the biggest UX wins over ad-hoc agent loops.

---

## 12. Plugins (`reigner.plugins`)

Plugins are extension points for things the package can't anticipate.

```python
from reigner.plugins import Plugin

class AuditPlugin(Plugin):
    name = "audit"

    async def before_tool_call(self, call, state):
        log.info("tool_call", name=call.name, args=call.args, session=state.session_id)
        return call

    async def after_tool_call(self, call, result, state):
        log.info("tool_result", name=call.name, truncated=result.truncated)
        return result

    async def on_compaction(self, state, level):
        log.info("compaction", level=level, tokens=state.token_count)

    async def on_final_answer(self, answer, state):
        return answer

    async def on_error(self, error, state):
        log.error("agent_error", error=str(error))
```

Hooks: `before_tool_call`, `after_tool_call`, `on_compaction`, `on_final_answer`, `on_error`, `on_oracle_escalation`, `on_steering`.

Concrete examples shipping with Reigner:

- `reigner.plugins.metrics.MetricsPlugin` — OpenTelemetry spans around tool calls and loop events (needs the `otel` extra; an OTLP integration point, not a telemetry product).
- `reigner.plugins.pii_redact.PiiRedactPlugin` — strip configured regex patterns out of tool results and the final answer.

An earlier draft also listed `audit` (JSON log of every event) and `rate_limit` (delay tool calls). Both were dropped: `audit` is redundant with the session store (§11), which already persists the full event stream, and with external observability sinks; `rate_limit` could only throttle domain tool calls via `before_tool_call`, never the model-adapter calls its name implied (those are the adapter's concern — see `RateLimitError` in §5). Either can return later if a concrete need appears.

Configured in `reigner.yaml`:

```yaml
plugins:
  - reigner.plugins.metrics.MetricsPlugin   # zero-arg — bare class path resolves
  - mypackage.observability:redactor        # PiiRedactPlugin instance (takes patterns)
```

---

## 13. Configuration (`reigner.yaml`)

The single source of truth for a Reigner agent.

```yaml
name: my_research_agent
version: 0.1.0

model:
  provider: anthropic
  name: claude-opus-4-7
  temperature: 0.2

oracle:
  provider: anthropic
  model: claude-opus-4-7-extended  # or a different provider entirely

settings:
  max_iterations: 25
  context_budget_tokens: 100000
  max_tool_result_chars: 4000
  tool_result_char_limits:
    read_artifact_file: 8000
    grep_artifact: 6000
    get_json_field: 8000
  nudge_interval: 3
  max_consecutive_errors: 3
  max_session_notes: 20
  history_keep_recent: 3
  compaction_thresholds: [0.80, 0.90, 0.95]
  parallel_reads: true
  timeout_seconds: 120

role:
  cascade:
    - recipe
    - user
    - project
  skills:
    - citation_strict
    - targeted_retrieval

tools:
  artifacts:
    root: library/artifacts
    schema: ./schema.yaml          # path to ArtifactSchema YAML scaffolded at init
  search:
    type: bm25
    index_path: search-index/documents.json
  custom:
    - mypackage.tools:get_market_cap

sessions:
  store_path: ./.reigner/sessions
  auto_save: true

plugins:
  - reigner.plugins.metrics.MetricsPlugin

eval:
  cases: eval/cases.yaml
  checks:
    - faithfulness
    - repeated_calls
    - coverage
```

---

## 14. CLI (`reigner`)

```
reigner init <name> [--recipe <name> | --blank | --guided]
    Scaffold a Reigner project. Three modes; default is --guided. All modes
    produce the same project layout (see §9.1).

    --guided  (default)
        Interactive Q&A about the user's domain, source documents, question
        shape, and citation strictness; uses a model to generate REIGNER.md
        and schema.yaml tailored to the answers. Asks before scaffolding the
        starter extractors/my_extractor.py — the only generated file that
        runs code, so it gets an explicit confirmation gate. Requires an
        API key in the environment; falls back to printing setup instructions
        and offering --blank if no key is present.

    --recipe <name>
        Copies the recipe's bundled REIGNER.md, reigner.yaml, schema.yaml,
        and extractor stub into the project verbatim. No LLM call. For users
        who know they want a known shape (document_qa, code_navigator).

    --blank
        Empty stubs only. No LLM call, fully offline. For users who want
        full manual control or have no API key configured.

reigner ingest [--pipeline <module:obj>] [--source <path>]
    Run an ingestion pipeline; logs progress, idempotent.

reigner chat
    Interactive REPL with steering. Enter = interrupt-steer; Alt+Enter = queue-steer.

reigner chat --print "<query>" [--json]
    One-shot run. --print emits final answer to stdout. --json emits the event
    stream as ND-JSON, one event per line. For scripting and CI.

reigner eval [--case <name>] [--check <name>]
    Run eval suite. Outputs a markdown scorecard.

reigner inspect [artifacts|index|role|tools|session <id>]
    Introspect what the harness sees. `inspect role` prints the composed ROLE.

reigner session list|fork|replay|export|import|tree
    Session management.

reigner serve [--http | --mcp] [--port 8000]
    Run as HTTP server (SSE) or MCP server.
```

`reigner init` is the make-or-break DX moment. Within 60 seconds a developer should have a working agent answering questions over a sample corpus. The --guided default exists because most users start from scratch on their own domain; --recipe is the path for users who already know they want a known shape.

---

## 15. Eval (`reigner.eval`)

Most agent libraries treat eval as BYO. Reigner ships opinionated checks because eval is part of the trust story.

```python
from reigner.eval import EvalSuite, EvalCase

suite = EvalSuite([
    EvalCase(
        query="What were Apple's R&D expenses in 2024?",
        expected_citations=["AAPL/2024/metrics.json#research_and_development"],
        forbidden_phrases=["I think", "approximately"],
        expected_clarification=False,
    ),
    EvalCase(
        query="What was the company's revenue?",  # ambiguous — which company?
        expected_clarification=True,
    ),
])

results = await suite.run(harness, checks=["faithfulness", "repeated_calls"])
```

### 15.1 Built-in checks

| Check | What it verifies |
|---|---|
| `faithfulness` | Every numeric claim in the final answer maps to a registered citation. |
| `repeated_calls` | Flags tool-call loops or redundant identical calls. |
| `entity_resolution` | For ambiguous queries, did the agent clarify or guess? |
| `coverage` | Did the agent retrieve the artifacts that contain the answer? |
| `latency_cost` | Token budgets and wall-clock time per case. |

### 15.2 Output

`reigner eval` emits a markdown scorecard:

```
## Eval results — 2026-05-06

| Case | Faithfulness | Repeated calls | Coverage | Cost |
|---|---|---|---|---|
| apple_rnd_2024 | ✓ | ✓ | ✓ | $0.018 |
| ambiguous_revenue | ✓ (clarified) | ✓ | n/a | $0.004 |
| msft_buyback_2023 | ✗ — claim "$67B" not cited | ✓ | ✓ | $0.022 |
```

---

## 16. Server (`reigner.server`)

Optional. For developers who want to deploy.

- `reigner serve --http` — FastAPI app with `POST /run` (SSE streaming) and `GET /health`. Mirrors the ApolloScope gateway shape.
- `reigner serve --mcp` — exports registered tools as an MCP server. Any Reigner tool is also an MCP tool, callable by Claude Desktop, Cursor, Cline, mcp-agent, and friends.

The MCP export means: developers can build their domain tools once with `@tool`, get a Python callable AND an MCP server. This is the interop story.

---

## 17. The `document_qa` recipe (v0 hero)

This is the recipe that proves the design works. It wires every piece together for retrieval-over-compiled-knowledge.

### 17.1 What it includes

- An `ArtifactSchema` matching the ApolloScope-style layout (`{entity}/{version}/...`).
- An `ArtifactStore` with the six artifact tools.
- A `Bm25Index` reading from `search-index/documents.json`.
- The pseudo-tools: `save_note`, `request_clarification`, `escalate_to_oracle`.
- A bundled `REIGNER.md` template teaching the targeted-retrieval grammar, copied into the project by `reigner init --recipe document_qa` (§9, §14).
- The skills: `citation_strict`, `clarify_when_ambiguous`, `targeted_retrieval`.
- Tuned `reigner.yaml` defaults for retrieval workloads.

### 17.2 Build call

```python
from reigner.recipes import document_qa

harness = document_qa.build(
    artifacts_root="library/artifacts",
    index_path="search-index/documents.json",
    schema=document_qa.SCHEMA,            # default ApolloScope-style schema
    role_overrides={"identity": "..."},   # tweak parts of the bundled ROLE
    model="claude-opus-4-7",
)
```

### 17.3 Reference corpus for v0 launch

To prove the recipe works on something other than NIRF without revealing ApolloScope, v0 ships with a working example over a public corpus. **Recommended: SEC 10-K filings for 5 large-cap companies over 3 years.** Reasoning:

- Public, structured (Item 1, 1A, 7, 8…), comparable across years, comparable across companies.
- Repeated entities, repeated metrics — the same shape that makes retrieval discipline matter.
- Strong citation culture; questions like "What was Apple's R&D in 2024?" have a clear right answer with a clear locator.
- The demo lands instantly with technical and finance-adjacent audiences.

The example lives in `examples/sec_10k/` with a README, a tiny ingestion script, and 20 eval cases.

---

## 18. The `code_navigator` recipe (contrast)

A deliberately Flue-shaped recipe so the comparison is fair and developers can pick the right tool.

- Uses `FsTools` (raw `fs_read`, `fs_grep`, `fs_glob`, `fs_ls`).
- No artifact schema.
- No citation skills.
- ROLE oriented around exploration rather than grounding.

Documented as: *"Use this when your corpus is unstructured, when your agent must write, or when the work is closer to coding than to research. For most retrieval use cases, prefer `document_qa`."*

---

## 19. What's deliberately out of scope for v0

Calling these out so they don't sneak back in during the build:

- Multi-agent orchestration (handoffs, swarms, graphs).
- Sandbox / runtime (containers, VMs).
- Hosted platform / cloud.
- Built-in vector store. The `SearchIndex` interface is pluggable; vector backends are contributable.
- LLM extractor library. Domain-specific.
- Frontend. The event protocol is the contract; UIs are downstream.
- Sub-agents / specialized assistants.
- Terminal UI as a primary surface. CLI is utility-grade.
- Self-modification / agent-edits-itself.
- More than two recipes. `document_qa` and `code_navigator` only.
- Concurrency control on a single session. The `Harness` is immutable and shared, so independent sessions run in parallel safely. But two in-flight runs resuming the *same* `session_id` both append to one JSONL via `auto_save` and race. v0 documents the contract as "one live run per `session_id` at a time"; a per-session lock (or rejecting a concurrent resume with HTTP 409) is a later hardening step. This surfaces first at the HTTP server (§16), where a retrying client or two tabs make it easy to trigger.
- Per-request profile on a *resumed* session. New sessions honor their `profile` (§6.3), but `Session.load` currently rebuilds resumed sessions at `profile="full"` regardless of the requested profile. So a `read_only` request that carries a `session_id` silently runs with full tool access. v0 documents this; threading `profile` through `Session.load` (and fork/replay) is a follow-up if per-request gating on resumes is needed.

---

## 20. Build order

A v0 sequence that gets to a working public release. Solo-developer estimate.

| Week | Milestone |
|---|---|
| 1 | `harness/` core: loop, events, state, OpenAI + Anthropic adapters. `tools/base.py` decorator. `tools/pseudo/`. `config.py`. Manually wired test agent works end-to-end. |
| 2 | `truncation.py`, `compaction.py`, `nudges.py`, `cache.py`, `parallel.py`, `oracle.py`. All G1–G11 in place with unit tests. |
| 3 | `tools/artifacts/`, `artifacts/` write side, `tools/search/bm25.py`. The artifact + BM25 surface works. |
| 4 | `recipes/document_qa/` built on top. Reference implementation over SEC 10-Ks. The demo notebook works. |
| 5 | `cli/` (init, chat, ingest, inspect). `ingestion/` skeleton. `role/` cascade composer. `skills/` first three modules. |
| 6 | `eval/` with faithfulness + repeated_calls + coverage. `tools/fs/` raw tier. `recipes/code_navigator/` contrast example. |
| 7 | `sessions/` with fork/replay/tree. `plugins/` system. `server/` HTTP + MCP export. Steering implementation. |
| 8 | Buffer week: docs site, examples, polish, public release. |

That's a real two-month build at one engineer. Halve it with two; double it if you also need to learn a model adapter you haven't used before.

---

## 21. Acceptance criteria for v0

The release is shippable when all of these are true:

1. `pip install reigner && reigner init demo --recipe document_qa && cd demo && reigner ingest && reigner chat` works on a clean machine in under 5 minutes against the SEC 10-K example.
2. The `document_qa` recipe answers 18+ of 20 eval cases correctly with valid citations.
3. The faithfulness eval flags every hallucinated number.
4. A second developer can build a custom recipe (different schema, different ROLE) without modifying Reigner's source.
5. The MCP export works: any `@tool`-decorated function can be served via `reigner serve --mcp` and called from Claude Desktop.
6. Sessions can be forked, replayed, and exported. A query replayed against a different model produces a different answer that's diff-able against the first.
7. The CLI emits `--json` output that's a valid event stream consumable by `jq`.
8. Docs cover: install, quickstart, the document_qa recipe, the artifact schema, writing your own tool, writing your own recipe, evaluation.

---

## 22. Open questions to resolve before week 1

1. **Async-first or sync-first?** The spec assumes async (G11 needs it; streaming is naturally async). Sync wrappers for tests/scripts are easy. Confirm.
2. **`ArtifactSchema` declarative-only, or also code?** Spec is declarative with YAML support. ApolloScope's was effectively code. Confirm declarative is enough.
3. **Recipes own `reigner.yaml` or generate it?** ✅ Resolved: recipes generate at init time. The recipe's bundled `REIGNER.md`, `reigner.yaml`, `schema.yaml`, and extractor stub are copied into the user's project verbatim by `reigner init --recipe <name>`. After init the recipe is no longer referenced; the project owns its own files (§9, §14).
4. **MCP export — schemas MCP-clean from day one?** Yes, with the `@tool` decorator enforcing constraints (no positional-only args, no `**kwargs`, JSON-serializable returns). Costs a little flexibility, gains interop.
5. **Default model adapter?** ✅ Resolved: OpenAI is the default recipe adapter. All three providers (OpenAI, Anthropic, Gemini) are first-class — `harness/adapters/{openai,anthropic,gemini}.py` ship in T-04 — but `document_qa` and `reigner.yaml` defaults point at OpenAI. Earlier draft preferred Anthropic for prompt caching; the OpenAI Responses API also caches stable prefixes automatically and the cost/availability profile is friendlier as the out-of-the-box default. Anthropic remains the natural oracle pick (§5.5).
6. **Naming of the guardrails: G1–G11 or descriptive only?** I picked G1–G11 because internal communication needs short identifiers. Public docs should still use names. Confirm.
7. **Session storage: `~/.reigner/sessions/` or `./.reigner/sessions/`?** ✅ Resolved: project-local at `./.reigner/sessions/`. Same reasoning as §9 — runtime state belongs to the project, not the machine. The `.gitignore` scaffolded by `reigner init` excludes this directory.
8. **`code_navigator` in v0 or v1?** Spec has it in v0 as a contrast. Could push to v1 if week 6 is tight.
9. **Runtime instruction cascade?** ✅ Resolved: no cascade. The project's `./REIGNER.md` is the single runtime source of truth. Recipes are init-time scaffolds; there is no `~/.reigner/REIGNER.md`. Skills remain the only on-demand layer (§9).
10. **`reigner init` default mode?** ✅ Resolved: `--guided` is the default. Most users start from scratch on a domain that no recipe covers. `--recipe` and `--blank` are the explicit alternatives (§14).

---

## Appendix A — Glossary

- **Harness** — the configured loop + tools + ROLE + model. Immutable.
- **Session** — one conversation. Durable, forkable. Holds history, scratchpad, cache.
- **Artifact** — a compiled output of ingestion: a section, a metadata blob, a metrics file.
- **ArtifactStore** — the read-side tool surface bound to a schema and a root.
- **ArtifactSchema** — the declared layout of artifacts on disk.
- **Recipe** — a complete working harness wiring for one shape of problem.
- **Skill** — an on-demand-loaded instruction module added to the ROLE.
- **Plugin** — a hook-based extension that runs around the loop.
- **Pseudo-tool** — a tool name the model uses but that's intercepted locally (`save_note`, `escalate_to_oracle`).
- **Profile** — a named tool subset (`full`, `read_only`, `eval`).
- **Oracle** — a more capable model invoked for one turn via `escalate_to_oracle`.
- **REIGNER.md** — the project's instruction file at repo root; the single runtime source of truth for the agent (§9).

---

## Appendix B — Reference: how this maps from ApolloScope

For internal reference only; not in public docs.

| ApolloScope concept | Reigner equivalent |
|---|---|
| `agent.py` loop | `reigner.harness.loop` |
| H1–H11 | G1–G11 |
| `library-mcp` tools | `reigner.tools.artifacts` |
| `analytics-mcp` (NIRF-specific) | User-defined `@tool`s |
| `agent.yaml` | `reigner.yaml` |
| ApolloScope's ROLE.md | `recipes/document_qa/REIGNER.md` (template copied into the user's project at init; §9) |
| `library/artifacts/{nirf_id}/{year}/` | `ArtifactSchema(entity_path="{entity_id}/{version}")` |
| `documents.json` BM25 sidecar | `tools.search.Bm25Index` |
| FastAPI gateway | `reigner.server.fastapi_app` |
| `nirf_id`, `alias_resolver`, scorecard | None — domain-specific, stays in ApolloScope |

The carve-out direction: ApolloScope itself depends on Reigner once Reigner is published. If ApolloScope can't be refactored to consume Reigner cleanly, the abstractions are wrong.

---

*End of v0 spec.*
