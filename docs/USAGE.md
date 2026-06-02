# Reigner — usage guide

A **living, hands-on guide to what Reigner actually does today** — written so a
dev who has never seen the internals can go *install → scaffold → ingest → chat*
by following it top to bottom.

It's derived from the shipped code and CLI: every feature carries a status flag,
and the flags were verified by **running the commands**, not by reading docs or
task lists.

> **Status legend**
> - ✅ **shipped** — works today, exercised below.
> - 🟡 **partial** — usable but incomplete; caveats called out inline.
> - ⏳ **planned** — scaffolding exists, behavior does not yet. Linked to its issue.

A note on the examples: commands that run **offline** (`init`, `ingest
--dry-run`, `inspect`, `serve`) show **real, pasted output**. Commands that need
a live model and would spend tokens (`chat`, a full `ingest` extraction) show
the exact command plus a **representative** output block, clearly marked
`# representative output`.

---

## 1. Quick start

### Install

```bash
uv add reigner
```

Reigner ships a thin core; each capability is an opt-in extra:

| Extra | Pulls in | You need it for |
|---|---|---|
| `reigner[anthropic]` | Anthropic SDK | `chat`/ingest with Claude models |
| `reigner[openai]` | OpenAI SDK | `chat`/ingest with GPT models |
| `reigner[gemini]` | Google GenAI SDK | `chat`/ingest with Gemini models |
| `reigner[server]` | FastAPI + uvicorn | `reigner serve --http` |
| `reigner[mcp]` | MCP libs | MCP export (⏳ not wired yet) |
| `reigner[ingestion]` | PyMuPDF loaders | PDF/URL ingestion (**AGPL** — see README) |
| `reigner[otel]` | OpenTelemetry API | the metrics plugin |
| `reigner[all]` | everything above | kitchen sink |

Confirm the install:

```console
$ reigner version
0.0.0
```

### Mental model (one paragraph)

A Reigner project is a **directory you scaffold once**. You drop raw documents
into it and run a one-time **ingestion** step that *compiles* them into bounded,
schema-aware **artifacts** plus a search index. The agent never touches your raw
files — at `chat` time it queries the compiled artifacts through a small set of
**read-only, self-describing tools**, and is steered by a single instruction
file, `REIGNER.md`. Everything the agent does is streamed as typed events and
saved to a durable, forkable **session** on disk. That's the whole loop:
*compile knowledge once, query it faithfully, with citations.*

---

## 2. Feature status

Each row was checked against real behavior (see the section linked under "How to
test"). Where a command needs a model, the status reflects the code path; the
output in Section 3 is marked representative.

| Feature | Status | Command / API | How to test |
|---|---|---|---|
| Scaffold — blank | ✅ | `reigner init NAME --blank` | [Section 3.1](#31-scaffold-a-project--reigner-init) |
| Scaffold — guided (default) | ✅ | `reigner init NAME --guided` | [Section 3.1](#31-scaffold-a-project--reigner-init) |
| Scaffold — recipe | ⏳ | `reigner init NAME --recipe X` | not yet bundled |
| Ingest (compile docs) | ✅ | `reigner ingest` | [Section 3.2](#32-ingest-your-documents--reigner-ingest) |
| Ingest dry-run | ✅ | `reigner ingest --dry-run` | [Section 3.2](#32-ingest-your-documents--reigner-ingest) |
| Chat — REPL | ✅ | `reigner chat` | [Section 3.3](#33-chat-with-your-agent--reigner-chat) |
| Chat — one-shot / JSON | ✅ | `reigner chat --print Q [--json]` | [Section 3.3](#33-chat-with-your-agent--reigner-chat) |
| Inspect role/config/tools | ✅ | `reigner inspect {role,config,tools}` | [Section 3.4](#34-inspect-the-project--reigner-inspect) |
| Inspect artifacts/index | ✅ | `reigner inspect {artifacts,index}` | [Section 3.4](#34-inspect-the-project--reigner-inspect) |
| Sessions — fork/replay/tree | 🟡 | Python API (no CLI yet) | [Section 3.5](#35-sessions-fork--replay--tree--python-api) |
| Serve — HTTP / SSE | ✅ | `reigner serve --http` | [Section 3.6](#36-serve-the-agent--reigner-serve) |
| Serve — MCP export | ⏳ | `reigner serve --mcp` | [Section 3.6](#36-serve-the-agent--reigner-serve) |
| Plugins — metrics, PII redact | ✅ | `plugins:` in `reigner.yaml` | [Section 3.7](#37-plugins) |
| Skills (on-demand modules) | ⏳ | `role.skills:` in `reigner.yaml` | [Section 5](#5-known-gaps--not-yet-wired) |
| Eval suite | ⏳ | (no CLI yet) | [Section 5](#5-known-gaps--not-yet-wired) |

---

## 3. Walkthrough

One worked example threads the whole section: a **document-QA agent over a tiny
corpus**. Each step ends in a runnable command. Follow them in order and you'll
have a working project by Section 3.4 (and a talking agent by Section 3.3 once you add a key).

### 3.1 Scaffold a project — `reigner init`

`init` has three modes:

- `--blank` — copies empty, offline stubs. **No model needed.** Best for
  following this guide.
- `--guided` — *the default*; an interactive Q&A that asks a model to generate
  your `REIGNER.md`/`schema.yaml`/extractor. ✅ Needs a model key.
- `--recipe NAME` — ⏳ would copy a bundled recipe, but **no recipes ship yet**
  (`--help` says *"not yet bundled"*).

Add `--force` to overwrite scaffold files when the target directory is non-empty.

We'll use `--blank`:

```console
$ reigner init mydocs --blank
✓ Scaffolded mydocs/ (blank mode)

mydocs/
├── eval/
│   └── cases.yaml
├── extractors/
│   ├── __init__.py
│   ├── my_extractor.py
│   └── pipeline.py
├── library/
│   ├── artifacts/
│   └── raw/
├── search-index/
├── .env.example
├── .gitignore
├── README.md
├── REIGNER.md
├── reigner.yaml
└── schema.yaml

Next:
  cd mydocs
  cp .env.example .env   # add your API key
  uv run reigner --help
```

What each piece is (full reference in [Section 4](#4-configuration-reference)):

| Path | Role |
|---|---|
| `reigner.yaml` | model, settings, tool wiring |
| `REIGNER.md` | the agent's instructions (loaded once at session start) |
| `schema.yaml` | declared shape of your compiled artifacts |
| `extractors/` | your `LLMExtractor` subclass + the ingestion `pipeline` |
| `library/raw/` | **you drop source docs here** |
| `library/artifacts/` | populated by `reigner ingest` |
| `search-index/` | BM25 sidecar, populated by ingestion |

```console
$ cd mydocs
```

### 3.2 Ingest your documents — `reigner ingest`

**Step 1 — add a corpus.** Drop a couple of markdown files into `library/raw/`.
For this example:

```text
library/raw/faq.md        # a short product FAQ
library/raw/security.md   # a security blurb
```

**Step 2 — wire the pipeline.** The blank scaffold ships `extractors/pipeline.py`
and `extractors/my_extractor.py` **fully commented out**, and `schema.yaml`
empty. A bare `reigner ingest` against the untouched scaffold therefore fails
loudly — by design, not silently:

```console
$ reigner ingest --dry-run
✗ 'extractors.pipeline' has no attribute 'pipeline'. available: (none)
```

You need three small edits before ingesting:

1. **`schema.yaml`** — declare what you extract (must be a YAML mapping, not all
   comments):

   ```yaml
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
   ```

2. **`extractors/my_extractor.py`** — a real `LLMExtractor` subclass. Note
   `schema` and `model` are **class attributes** (the commented scaffold example
   passes `schema=` to the constructor — that's wrong; `__init__` only takes an
   optional `adapter`):

   ```python
   from reigner.artifacts import ArtifactSchema
   from reigner.ingestion import ExtractionResult, LLMExtractor


   class MyExtractor(LLMExtractor):
       schema = ArtifactSchema.from_yaml("schema.yaml")
       model = "openai:gpt-4o"
       PROMPT = "Summarize this document in one line."

       async def extract(self, raw: bytes, meta: dict) -> ExtractionResult:
           # call_model takes (prompt, input_text) and returns a parsed JSON dict.
           data = await self.call_model(self.PROMPT, raw.decode("utf-8", "ignore"))
           return ExtractionResult(
               sections={"document_summary": data["summary"]},
               json_artifacts={"metadata.json": {"entity_id": meta["entity_id"], "version": "v1"}},
           )
   ```

   The base class gives you, for free: model-adapter wiring (`model =
   "provider:model_id"`, or pass an `adapter` to `__init__`), transient-error
   retries (`max_retries`, default 2; `base_backoff_seconds`, default 1.0),
   validation of your `ExtractionResult` against `schema`, deterministic
   idempotency keys, token/cost accounting (set `pricing` to get non-zero
   `cost_usd`), and a default `preprocess_pdf` (PyMuPDF). Inside `extract` you
   call `call_model(prompt, input_text)` for a single-shot JSON request, or
   `preprocess_pdf(raw)` for text extraction — **override `preprocess_pdf`** for
   OCR/multi-column, or to swap out the AGPL PyMuPDF dependency. Failures raise
   the ingestion error taxonomy: `TransientError`, `ExtractionError`, and
   `ValidationError`.

3. **`extractors/pipeline.py`** — assemble loaders → transforms → writers into a
   top-level `pipeline` symbol (what `reigner ingest` resolves by default):

   ```python
   from reigner.ingestion import IngestionPipeline
   from reigner.ingestion.loaders import MdLoader
   from reigner.ingestion.writers import ArtifactWriter, Bm25IndexWriter

   from .my_extractor import MyExtractor

   pipeline = IngestionPipeline(
       loaders=[MdLoader()],
       transforms=[MyExtractor()],
       writers=[
           ArtifactWriter(root="library/artifacts", schema=MyExtractor.schema),
           Bm25IndexWriter(path="search-index/documents.json"),
       ],
       on_error="skip",
   )
   ```

**Step 3 — dry-run** to see the discovery plan without writing anything or
calling a model (fully offline):

```console
$ reigner ingest --dry-run
dry run · source: library/raw
would ingest 2 source(s):
  library/raw/faq.md → MdLoader
  library/raw/security.md → MdLoader
```

**Step 4 — the real compile.** This calls your extractor's model, so it needs a
key in `.env` (`cp .env.example .env` and fill in `OPENAI_API_KEY=...`):

```console
$ reigner ingest
# representative output
✓ loaded 2 documents
✓ extracted 2 entities → library/artifacts/
✓ built BM25 index → search-index/documents.json
```

**All `ingest` flags:**

| Flag | Effect |
|---|---|
| `--pipeline MODULE:OBJ` | Dotted path to an `IngestionPipeline`. Defaults to `extractors.pipeline:pipeline`. |
| `--source PATH` | Directory or file of raw docs. Defaults to `library/raw` **only when `--pipeline` is omitted** — an explicit `--pipeline` requires an explicit `--source`. |
| `--json` | Emit one event per line as NDJSON instead of rich progress. |
| `--on-error {raise,skip,dead_letter}` | Override the pipeline's `on_error` policy. |
| `--concurrency N` | Override the pipeline's worker semaphore. |
| `--dry-run` | Discover sources, print the file → loader plan, exit without writes. |

#### Loaders, writers, and custom pipelines

The pipeline maps each source file to a **loader** by extension. Four ship in
`reigner.ingestion.loaders`:

| Loader | Handles |
|---|---|
| `MdLoader` | Markdown / text |
| `PdfLoader` | PDF (via PyMuPDF — **AGPL**, the `[ingestion]` extra) |
| `JsonLoader` | JSON documents |
| `UrlLoader` | Fetches an `http(s)` URL |

Writers (`reigner.ingestion.writers`): `ArtifactWriter` (compiled artifacts on
disk) and `Bm25IndexWriter` (the search sidecar). List the loaders you need and
the writers you want — both must be non-empty.

`IngestionPipeline` takes more than the four fields shown above. Full signature:

```python
IngestionPipeline(
    loaders=[MdLoader(), PdfLoader(), JsonLoader()],  # ≥1
    transforms=[MyExtractor()],          # EXACTLY ONE in v0 — more raises ValueError
    writers=[ArtifactWriter(...), Bm25IndexWriter(...)],  # ≥1
    concurrency=4,                       # worker semaphore
    on_error="raise",                    # "raise" | "skip" | "dead_letter"
    dead_letter_path="dead/",            # REQUIRED when on_error="dead_letter"
    identifiers_fn=None,                 # optional: derive (entity_id, version) per source
    source_id_fn=None,                   # optional: stable source id for idempotency
    session_id=None,                     # optional: tag the run
)
```

To run a non-default pipeline (e.g. one per corpus), point `--pipeline` at it and
pass an explicit `--source`:

```console
$ reigner ingest --pipeline mypkg.pipelines:web_pipeline --source urls.txt
```

`run` returns an `IngestionReport` (counts + any `SourceFailure` entries), so you
can also drive ingestion from Python instead of the CLI.

### 3.3 Chat with your agent — `reigner chat`

`chat` builds the harness from `reigner.yaml`, auto-loads your project `.env`,
and opens a REPL — or runs one-shot with `--print`. It needs a model key.

**Interactive REPL:**

```console
$ reigner chat
› What does Orbit cost?
# representative output
Orbit is $8 per user per month. [faq.md]
›
```

REPL controls:

| Key / command | Action |
|---|---|
| `Enter` | Submit a prompt — or, while a run is in flight, **steer** it (interrupt mode). |
| `Alt+Enter` | Steer the in-flight run in **queue** mode (apply after the current step). |
| `Ctrl+C` | Cancel the current run. |
| `/exit`, `/quit`, `Ctrl+D` | Quit the REPL. |

> Steering's `interrupt` mode is partially wired
> ([#48](https://github.com/Construct-Lab/reigner/issues/48)): today it queues
> rather than truly preempting the in-flight model call. `queue` works as
> described.

**One-shot** (stdout is just the final answer — scriptable):

```console
$ reigner chat --print "What does Orbit cost?"
# representative output
Orbit is $8 per user per month.
```

**Structured events** (one JSON object per line — every tool call, citation, and
the final answer — for piping into other tools):

```console
$ reigner chat --print "What does Orbit cost?" --json
# representative output
{"event": "tool_call", "name": "bm25_search", "args": {"query": "cost"}}
{"event": "citation", "path": "faq.md", "quote": "$8 per user per month"}
{"event": "final_answer", "text": "Orbit is $8 per user per month."}
```

> Pass `-c path/to/reigner.yaml` to point at a non-default config.

### 3.4 Inspect the project — `reigner inspect`

`inspect` is your offline window into how a config resolves — no model needed.
Five subcommands, each accepting `-c/--config PATH` (default `./reigner.yaml`):

**`config`** — the resolved settings table, showing which values came from your
file vs. defaults:

```console
$ reigner inspect config
mydocs  v0.1.0
config: /path/to/mydocs/reigner.yaml

model: openai:gpt-4o  (temp=0.2)
role.file: REIGNER.md
sessions.store_path: ./.reigner/sessions

                        settings
┏━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ field                   ┃ value            ┃ source  ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ max_iterations          │ 25               │  file   │
│ context_budget_tokens   │ 100000           │  file   │
│ max_tool_result_chars   │ 4000             │  file   │
│ compaction_thresholds   │ (0.8, 0.9, 0.95) │  file   │
│ parallel_reads          │ True             │  file   │
└─────────────────────────┴──────────────────┴─────────┘
```

**`role`** — prints the `REIGNER.md` the agent will load, its resolved path, and
the configured skills list.

**`tools`** — enumerates every tool the harness would register from this config.
With only the built-ins wired you get four pseudo-tools; once you uncomment
`tools.artifacts` and `tools.search` in `reigner.yaml` (see [Section 4](#4-configuration-reference)),
the artifact and BM25 tools appear:

```console
$ reigner inspect tools
                            wired tools
┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━┓
┃ name                  ┃ readonly ┃ pseudo ┃ cache ┃ source      ┃
┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━┩
│ save_note             │    ✓     │   ✓    │       │ builtin     │
│ request_clarification │    ✓     │   ✓    │       │ builtin     │
│ stop                  │    ✓     │   ✓    │       │ builtin     │
│ register_citation     │    ✓     │   ✓    │       │ builtin     │
│ read_artifact_file    │    ✓     │        │       │ artifacts   │
│ grep_artifact         │    ✓     │        │       │ artifacts   │
│ get_json_field        │    ✓     │        │       │ artifacts   │
│ list_documents        │    ✓     │        │       │ artifacts   │
│ list_versions         │    ✓     │        │       │ artifacts   │
│ get_section           │    ✓     │        │       │ artifacts   │
│ bm25_search           │    ✓     │        │   ✓   │ search:bm25 │
│ filtered_search       │    ✓     │        │   ✓   │ search:bm25 │
│ section_search        │    ✓     │        │   ✓   │ search:bm25 │
└───────────────────────┴──────────┴────────┴───────┴─────────────┘
```

**`artifacts`** — walks the configured artifact store and renders an entity
tree. Pass `--entity ID` (e.g. `--entity AAPL/2024`) to drill into a single
entity's sections and JSON artifacts. **`index`** — shows BM25 index health (doc
count, vocab, sections). Both require the corresponding `tools.*` block to be
configured, and `index` requires a populated index (run `ingest` first),
otherwise they print a helpful hint:

```console
$ reigner inspect index
no tools.search configured in reigner.yaml
hint: add tools.search.index_path (and `reigner ingest` to populate it).
```

After wiring `tools.search` and ingesting, `inspect index` reports the live
counts:

```console
$ reigner inspect index
# representative output
docs: 2 · vocab: 418 · sections: 9
```

### 3.5 Sessions: fork / replay / tree — Python API

Sessions are durable JSONL logs under `./.reigner/sessions/`, written
automatically by every `chat` run. They're **forkable and replayable** — the
foundation for A/B/C comparison of `REIGNER.md`/model/tool variants.

🟡 **The fork/replay/tree logic ships, but there is no `reigner session` CLI
yet** — the CLI commands are tracked in
[#21](https://github.com/Construct-Lab/reigner/issues/21) (still open). For now
the capability lives in the Python API. Forking and replay are methods on a
`Session`; listing and lineage live on `SessionStore` and the `tree` helpers:

```python
from reigner.harness.agent import Harness

harness = Harness.from_config("reigner.yaml")
session = harness.session()                 # new durable session
await session.run("What does Orbit cost?")  # the loop is async

# Branch off turn 2 into an independent, replayable child session.
branch = session.fork(at_turn=2)
await branch.run("...and how is data secured?")

# Replay the first N turns (e.g. to re-run them under a different model:
# build a Harness with the other model, load the session into it, replay).
restored = await session.replay(at_turn=2)
```

Browse and visualize what's on disk:

```python
from reigner.sessions import SessionStore, tree, build_forest

store = SessionStore("./.reigner/sessions")
for meta in store.list():
    print(meta.session_id, meta.title)

print(tree(store, session.id))   # this session's fork lineage
print(build_forest(store))       # every root → its branches
store.export(session.id, "out.jsonl")   # portable single-file export
```

### 3.6 Serve the agent — `reigner serve`

Expose the configured agent over HTTP with SSE streaming (needs
`reigner[server]`):

```console
$ reigner serve --http
# representative output
· listening on http://127.0.0.1:8000  (POST /run · GET /health)
```

Two endpoints:

- `GET /health` → `{"status": "ok", "name": ..., "model": ...}` — liveness +
  identity probe.
- `POST /run` → an SSE stream of the same typed events as `chat --json`. Body:
  `{"query": "...", "session_id": "optional", "profile": "full"}`.

Flags: `--host` (defaults to loopback; set `0.0.0.0` to expose), `--port`
(default `8000`), `-c` for a non-default config.

⏳ **MCP export is not implemented yet** — `--mcp` exits cleanly rather than
pretending to work:

```console
$ reigner serve --mcp
✗ --mcp is not yet implemented — the MCP export lands in a later change.
  Use `reigner serve --http` for now.
```

### 3.7 Plugins

Plugins hook into the loop without touching it. Two ship in the box; list their
dotted paths under `plugins:` in `reigner.yaml`:

- **`MetricsPlugin`** (`reigner.plugins.metrics`) — turns the loop into
  OpenTelemetry spans (one per tool call, plus markers for compaction, errors,
  steering). Needs the `otel` extra **and** an OTel provider configured in *your*
  app — without one, spans hit a no-op tracer (by design). See the README's
  Observability section.
- **`PiiRedactPlugin`** (`reigner.plugins.pii_redact`) — regex redaction of tool
  results before they reach the model. No extra dependency.

```yaml
plugins:
  - reigner.plugins.pii_redact.PiiRedactPlugin
  - reigner.plugins.metrics.MetricsPlugin
```

---

## 4. Configuration reference

### `reigner.yaml`

The project's resolved config. Key blocks (defaults shown are from the blank
scaffold):

```yaml
name: mydocs
version: 0.1.0

model:                       # the agent's model
  provider: openai
  name: gpt-4o
  temperature: 0.2

# oracle:                    # optional single-turn escalation
#   provider: anthropic
#   model: claude-opus-4-7

settings:                    # guardrail knobs (see `inspect config`)
  max_iterations: 25
  context_budget_tokens: 100000
  max_tool_result_chars: 4000
  nudge_interval: 3
  max_consecutive_errors: 3
  compaction_thresholds: [0.80, 0.90, 0.95]
  parallel_reads: true

role:
  file: REIGNER.md
  skills: []                 # on-demand skill modules (⏳ see Section 5)

tools:                       # commented out in the blank scaffold —
  artifacts:                 # uncomment to wire the artifact toolbox
    root: library/artifacts
    schema: ./schema.yaml
  search:                    # uncomment to wire BM25 search
    type: bm25
    index_path: search-index/documents.json
  # fs:                      # optional filesystem tool (read-only by default)
  #   root: .
  #   write_enabled: false
  custom: []

sessions:
  store_path: ./.reigner/sessions
  auto_save: true

plugins: []
```

> The `tools.artifacts` and `tools.search` blocks ship **commented out**. Until
> you uncomment them the agent has only the four built-in pseudo-tools, and
> `inspect artifacts`/`inspect index` print a hint instead of data (see
> [Section 3.4](#34-inspect-the-project--reigner-inspect)).

### `REIGNER.md`

The single runtime source of truth for agent behavior — loaded **once** at
session start. There is **no cascade** (no machine-global or per-recipe layer):
runtime behavior is reproducible from the project repo alone. The scaffold ships
a commented template with four sections to fill in: **Identity**, **Retrieval
grammar** (teach the model how to use the tools — docstrings aren't enough),
**Citation rules**, and **Clarification policy**.

### `.env`

Reigner **auto-loads your project `.env`** at CLI startup (resolved next to
`reigner.yaml`). Copy the scaffolded example and add your provider key:

```bash
cp .env.example .env
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# GOOGLE_API_KEY=...
```

### `./.reigner/` layout

Project-local runtime state (not machine-global — same reproducibility argument
as `REIGNER.md`):

- `./.reigner/sessions/` — durable session JSONL logs + per-session meta,
  written by `chat` and the sessions API.

---

## 5. Known gaps / not-yet-wired

Short list of what the scaffolding promises but doesn't do yet. Each links its
tracking issue.

- **`reigner session` CLI** — ⏳ no CLI; fork/replay/tree are Python-API only
  today ([Section 3.5](#35-sessions-fork--replay--tree--python-api)).
- **`reigner eval`** — ⏳ the `eval/cases.yaml` stub is scaffolded but there's no
  `eval` command and the `reigner.eval` package is empty.
- **`reigner init --recipe`** — ⏳ `--help` says *"not yet bundled"*; the
  `recipes/` package ships empty. Use `--blank` (or `--guided`) for now.
- **Skills** (`role.skills:`) — ⏳ the on-demand skill loader package is empty;
  the config key is accepted but does nothing yet.
- **`reigner serve --mcp`** — ⏳ exits with a "not yet implemented" message
  ([Section 3.6](#36-serve-the-agent--reigner-serve)).
- **Real-time steering interrupt** — 🟡 `mode="interrupt"` currently behaves like
  `queue` at the loop layer ([#48](https://github.com/Construct-Lab/reigner/issues/48)).

This doc is a hand-verified snapshot — when a track lands, its row here and in
[Section 2](#2-feature-status) should be updated to match.
