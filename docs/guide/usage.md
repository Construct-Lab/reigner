# Usage guide

This guide walks through Reigner end to end — install, scaffold a project, ingest
documents, and chat with cited answers — using the commands as they ship today.
Every feature in the [status table](#2-feature-status) is marked with where it stands.

> Just want a first cited answer fast? Start with the
> [Quickstart](quickstart.md) — the five-minute path on the `document_qa` recipe.
> This guide is the comprehensive reference.

> **Status legend**
> - ✅ **shipped** — works today.
> - 🟡 **partial** — usable but incomplete; caveats noted inline.
> - ⏳ **planned** — scaffolded but not yet functional; linked to its tracking issue.

Output shown for offline commands (`init`, `ingest --dry-run`, `inspect`, `serve`)
is real. Commands that call a model (`chat`, a full `ingest`) show a representative
output block marked `# representative output`.

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
| `reigner[ingestion]` | PyMuPDF loaders | PDF/URL ingestion (PyMuPDF is **AGPL-3.0**) |
| `reigner[otel]` | OpenTelemetry API | the metrics plugin |
| `reigner[all]` | everything above | kitchen sink |

Confirm the install:

```console
$ reigner version
0.6.0
```

### Mental model

A Reigner project is a **directory you scaffold once**. You drop raw documents
into it and run a one-time **ingestion** step that *compiles* them into bounded,
schema-aware **artifacts** plus a search index. The agent never touches your raw
files — at `chat` time it queries the compiled artifacts through a small set of
**read-only, self-describing tools**, and is steered by a single instruction
file, `REIGNER.md`. Everything the agent does is streamed as typed events and
saved to a durable, forkable **session** on disk.

---

## 2. Feature status

Each row was checked against real behavior (see the section linked under "How to
test"). Where a command needs a model, the status reflects the code path; the
output in Section 3 is marked representative.

| Feature | Status | Command / API | How to test |
|---|---|---|---|
| Scaffold — blank | ✅ | `reigner init NAME --blank` | [Section 3.1](#31-scaffold-a-project--reigner-init) |
| Scaffold — guided (default) | ✅ | `reigner init NAME --guided` | [Section 3.1](#31-scaffold-a-project--reigner-init) |
| Scaffold — recipe (`document_qa`) | ✅ | `reigner init NAME --recipe document_qa` | [Section 3.1.1](#311-the-document_qa-recipe) |
| Scaffold — recipe (`code_navigator`, multi-repo) | ✅ | `reigner init NAME --recipe code_navigator` | [Section 3.1.2](#312-the-code_navigator-recipe-multi-repo) |
| Ingest (compile docs) | ✅ | `reigner ingest` | [Section 3.2](#32-ingest-your-documents--reigner-ingest) |
| Ingest dry-run | ✅ | `reigner ingest --dry-run` | [Section 3.2](#32-ingest-your-documents--reigner-ingest) |
| Chat — REPL | ✅ | `reigner chat` | [Section 3.3](#33-chat-with-your-agent--reigner-chat) |
| Chat — one-shot / JSON | ✅ | `reigner chat --print Q [--json]` | [Section 3.3](#33-chat-with-your-agent--reigner-chat) |
| Chat — collapsed retrieval + run cost | ✅ | REPL recap · `--verbose`/`-v` · `/verbose` · `/expand` | [Section 3.3](#33-chat-with-your-agent--reigner-chat) |
| Inspect role/config/tools | ✅ | `reigner inspect {role,config,tools}` | [Section 3.4](#34-inspect-the-project--reigner-inspect) |
| Inspect artifacts/index | ✅ | `reigner inspect {artifacts,index}` | [Section 3.4](#34-inspect-the-project--reigner-inspect) |
| Sessions — list/show/tree/fork/replay | ✅ | `reigner session …` | [Section 3.5](#35-sessions-list--show--tree--fork--replay--reigner-session) |
| Serve — HTTP / SSE | ✅ | `reigner serve --http` | [Section 3.6](#36-serve-the-agent--reigner-serve) |
| Serve — MCP export | ⏳ | `reigner serve --mcp` | [Section 3.6](#36-serve-the-agent--reigner-serve) |
| Plugins — metrics, PII redact | ✅ | `plugins:` in `reigner.yaml` | [Section 3.7](#37-plugins) |
| Skills (on-demand modules) | ✅ | `role.skills:` in `reigner.yaml` | [Section 3.9](#39-skills--on-demand-instruction-modules) |
| Eval — scorecard / report | ✅ | `reigner eval [--report]` | [Section 3.8](#38-evaluate-your-agent--reigner-eval) |

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
- `--recipe NAME` — ✅ copies a bundled recipe over the shared layout. **Two
  ship today**: `document_qa` — question-answering over a corpus, the ingestion
  hero case (see [Section 3.1.1](#311-the-document_qa-recipe)) — and
  `code_navigator` — a read-only *sidecar* over one or more existing repos, the
  no-ingestion contrast case (see
  [Section 3.1.2](#312-the-code_navigator-recipe-multi-repo)). An unknown name
  fails loudly with the list of what's bundled.

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

#### 3.1.1 The `document_qa` recipe

`--blank` gives you empty stubs; `--guided` asks a model to generate your files.
The **recipe** is the middle path: a curated, ready-to-run project for the
common case — question-answering over a corpus of same-shaped documents — copied
in verbatim. It's the fastest 0→1, and unlike `--guided` it needs no model call
to scaffold.

```console
$ reigner init acme-docs --recipe document_qa
✓ Scaffolded acme-docs/ (document_qa recipe mode)

acme-docs/
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
  cd acme-docs
  cp .env.example .env   # add your API key
  # edit extractors/my_extractor.py — refine the extraction prompt
  # edit extractors/pipeline.py — name your entities
  reigner ingest
  reigner chat
```

Same tree as `--blank`, but the files are **filled in, not stubbed**:

| File | State out of the box |
|---|---|
| `reigner.yaml` | ✅ Tuned model / oracle / skills / tool wiring — runs as-is |
| `REIGNER.md` | ✅ Targeted-retrieval instructions over the real tool grammar |
| `schema.yaml` | ✅ The `document_qa` artifact shape (`document_summary`, `sections/*`, `insights/*`, `metadata.json`) |
| `extractors/pipeline.py` | ✅ Runnable pipeline wired to the recipe schema — one marked TODO is the entity-naming rule |
| `extractors/my_extractor.py` | ✅ A single-call `LLMExtractor` with a working generic prompt — **refine** it for your documents (only the `model` line is a TODO) |

A recipe is **init-time data, not runtime code**: after `init` the copied files
*are* your project, and the recipe is never referenced again (no cascade — see
[`REIGNER.md`](#reignermd)). So the only **required** work before `ingest` is
domain-specific: drop your documents in `library/raw/` and add an API key. The
pipeline, schema, and a generic extraction prompt run on their defaults — refine
the prompt for better extraction on your corpus, and edit the pipeline or schema
only to change how entities are named or what shape you extract.

An unknown recipe name fails loudly with what's available:

```console
$ reigner init x --recipe nope
✗ unknown recipe 'nope'. Available: code_navigator, document_qa.
```

#### 3.1.2 The `code_navigator` recipe (multi-repo)

`document_qa` compiles a corpus into artifacts and answers over them.
`code_navigator` is the **contrast case**: there is *no ingestion*. It's a
**sidecar** — a small project that lives in its own directory and points at one
or more repositories you already have. At `chat` time the agent reads across all
of them in a single conversation, so you can ask how a frontend call reaches its
backend route, or trace a shared name from where it's defined to where it's used
— **without merging the repos into a monorepo**. The target repos are read-only
by default and never modified.

This is the real-world "one agent over N repos" use case, and it's powered by
**multi-root filesystem tools** ([Section 4](#4-configuration-reference) covers
the config). Each repo is mounted under an arbitrary *name* that becomes a
top-level directory in the agent's virtual tree; the agent addresses files as
`name/path/to/file`, and unqualified `fs_grep`/`fs_glob` fan out across every
root at once.

**`init` prompts for your repos interactively** and writes them into
`reigner.yaml` — you don't hand-edit YAML to get started. Give each repo a name
and a path (relative, absolute, or `~/…`); an empty name finishes:

```console
$ reigner init cnav --recipe code_navigator
Repos to explore — add one or more. Each name becomes a top-level directory the
agent sees.
Path can be relative (to this project), absolute, or ~/...
Press Enter on an empty name to finish.
  Root name: backend
  Path to 'backend': ../api
  Root name: frontend
  Path to 'frontend': ../web
  Root name:                       # ← empty, finishes
✓ Scaffolded cnav/ (code_navigator recipe mode)

cnav/
├── .env.example
├── .gitignore
├── README.md
├── REIGNER.md
└── reigner.yaml

Next:
  cd cnav
  cp .env.example .env   # add your API key
  # edit reigner.yaml — point tools.fs.roots at your repos
  reigner chat
```

The tree is **lean by design** — no `schema.yaml`, `extractors/`, `library/`, or
`search-index/`. A sidecar reads live repos; it never compiles artifacts, so the
ingestion-shaped scaffolding is simply absent. What the prompts produced lands in
`tools.fs.roots`:

```yaml
tools:
  fs:
    roots:
      backend: ../api
      frontend: ../web
    write_enabled: false   # read-only is the safe default for a navigator
```

Any names, any number of repos — `backend`/`frontend` is just the placeholder.
Add `shared: ../shared-lib`, `infra: ~/code/infra`, and so on. Edit `roots`
freely after init; it's plain config. Names are validated (`[A-Za-z0-9_-]+`), and
a root that doesn't resolve to a real directory **fails loudly at `chat`
startup** rather than silently vanishing:

```console
$ reigner chat
✗ tools.fs.roots['backend'] does not exist or is not a directory: /abs/path/api (from '../api')
```

Pressing Enter on the very first name keeps the bundled `backend`/`frontend`
placeholders, so the file is still a valid, editable template you can fill in
later.

Once the roots point at real repos and you've added a key, explore across them:

```console
$ reigner chat --print "How does the web client call the login endpoint, and where is it handled in the api?"
# representative output
The web client posts to `/api/login` from frontend/src/api/auth.ts, which is
handled by login_view in backend/app/routes/auth.py. [1][2]
```

You can verify the wiring **entirely offline** (no key, no tokens) — the same
check used to validate this recipe. `inspect tools` shows the read-only fs tools
(`fs_read`, `fs_grep`, `fs_glob`, `fs_ls` — all `readonly`, source `fs`), and
driving them directly proves the fan-out. `fs_ls("")` lists the roots as the
top-level tree, and a single unqualified `fs_grep` returns matches from **both**
repos, each path root-prefixed:

```python
import asyncio
from reigner.config import ReignerConfig
from reigner.harness.agent import build_fs_tools

tools = {t.name: t for t in build_fs_tools(ReignerConfig.load("reigner.yaml"))}

async def demo():
    print(await tools["fs_ls"].run({"path": ""}))
    print(await tools["fs_grep"].run({"query": "/api/login"}))

asyncio.run(demo())
```

```python
# fs_ls — the roots ARE the top-level tree:
{'entries': [{'name': 'backend', 'type': 'dir', ...},
             {'name': 'frontend', 'type': 'dir', ...}], 'count': 2, ...}

# fs_grep — one call, both repos, paths root-prefixed:
{'matches': [{'path': 'backend/app/routes/auth.py', 'line_no': 2, ...},
             {'path': 'frontend/src/api/auth.ts',  'line_no': 2, ...}],
 'total_files_searched': 2, ...}
```

To let the agent **edit** the target repos (e.g. a refactor across repos), set
`write_enabled: true` — an `fs_write` tool then registers, resolving through the
same per-root sandbox. Left off (the default), the navigator explores without
risk.

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
loudly, not silently:

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
       model = "openai:gpt-5.5"
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
   idempotency keys, token/cost accounting (priced from `reigner.pricing` for
   any known model, or set `pricing` to override the rates), and a default
   `raw_to_text` (PyMuPDF). Inside `extract` you call `call_model(prompt,
   input_text)` for a single-shot JSON request, or `raw_to_text(raw)` for text
   extraction — **override `raw_to_text`** for HTML/OCR/multi-column, or to swap
   out the AGPL PyMuPDF dependency. (The old name `preprocess_pdf` still works as
   a deprecated alias for one release.) Failures raise the ingestion error
   taxonomy: `TransientError`, `ExtractionError`, and `ValidationError`.

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

The pipeline maps each source file to a **loader** by extension. Five ship in
`reigner.ingestion.loaders`:

| Loader | Handles |
|---|---|
| `MdLoader` | Markdown / text |
| `PdfLoader` | PDF (via PyMuPDF — **AGPL**, the `[ingestion]` extra) |
| `JsonLoader` | JSON documents |
| `HtmlLoader` | On-disk HTML (`.html` / `.htm`) |
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

#### Large & non-uniform corpora

Most corpora are **uniform** — many instances of the *same* shape. Every SEC
10-K has a business section, risk factors, and financials, so a schema that
*requires* those sections fits every document and minimal setup just works. That
assumption is baked into the artifact-schema model, and it breaks quietly on a
**non-uniform** corpus — documents of genuinely different shapes (a textbook, a
statute, a procedure manual) where no single required-section list fits all of
them. The failure surfaces late, at ingest, not at schema-authoring time.

`reigner init --guided` asks whether your corpus is uniform or mixed and
scaffolds accordingly; if you answered *mixed*, this is what it generated for you
and why. If you're building a pipeline by hand, this is the playbook.

> For an end-to-end worked example of this path on a real corpus — 100+ page SEC
> 10-K filings, map-reduce extraction, field-level citations — see the
> [SEC 10-K case study](sec-10k.md).

**Diagnose your axis.** A large or awkward corpus is usually failing on one of
three independent axes. Identify which before reaching for a tool:

| Axis | How it shows up | Reach for |
|---|---|---|
| **Size** — a document is too big for one model call | artifacts look fine but are quietly incomplete; the tail of long documents was never read | `MapReduceExtractor` (reads the whole document) |
| **Heterogeneity** — documents don't share a shape | `SchemaValidationError` → dead-letter on the documents that can't fill a `required` section | `generic_default()` + optional sections |
| **Extractability** — a PDF has no text layer | page count high, extracted text near-zero (a 200-page scan → a few hundred chars) | OCR upstream, or park it ([#87](https://github.com/Construct-Lab/reigner/issues/87)) |

**Reading the whole document.** `call_model(prompt, input_text)` is
**single-shot — it does not chunk**. It guards `max_input_chars` (default
`200_000`); the default `overflow_mode="warn"` **shouts a warning but still sends
the whole text** — it never silently drops the tail (`"error"` raises
`InputOverflowError`; `"truncate"` cuts to the cap and warns how much went). That
guard is how you *discover* a document is too big. When a document must be read in
full but doesn't
fit one call, subclass `MapReduceExtractor`. It opts out of the single-shot guard
(`max_input_chars = None`) because chunking already bounds every `call_model`
call — your subclass inherits that, nothing to set. It MAPs the text in
`chunk_chars`-capped windows (default `100_000` ≈ 25K tokens; pages are packed,
never split, so every page is seen), then REDUCEs the per-section fragments to
fit each section's `max_chars`. You supply two prompts; the base owns chunking,
fan-out, reduction, and the final size guard — `extract()` is inherited, you do
not write it.

**Uniform vs. non-uniform corpora.** A `required: true` section is enforced for
*every* document, so a required-section list is really a per-document-type
contract — it holds only when every document is that type. For a mixed corpus,
make topical sections `optional` (each document fills only what it covers), or
start from `ArtifactSchema.generic_default()` — a preset of corpus-agnostic
sections any document can fill:

```python
from reigner.artifacts import ArtifactSchema

schema = ArtifactSchema.generic_default()
# one required section: overview/topic_summary
# optional: key_concepts, entities_and_definitions, structure/outline,
#           notable_passages, citations/source_evidence
```

The trade-off vs. `document_qa_default()` (uniform corpora) is weaker
`section_search` targeting — there's no `constitution/fundamental_rights` bucket
to aim at — recovered by leaning on `bm25_search` over the generic sections.

**Worked example — a map-reduce extractor.** A `MapReduceExtractor` subclass for
a mixed corpus. The full version is what `reigner init --guided` writes to
`extractors/my_extractor.py` (and lives at
`reigner/cli/templates/my_extractor_mapreduce.py`); the shape:

```python
from typing import Any

from reigner.artifacts import ArtifactSchema
from reigner.ingestion import MapReduceExtractor


class MyExtractor(MapReduceExtractor):
    schema = ArtifactSchema.from_yaml("schema.yaml")
    model = "anthropic:claude-sonnet-4-6"

    # overview/topic_summary is synthesized by summarize() from the reduced
    # sections — don't ask the per-chunk map for it.
    MAP_EXCLUDE = frozenset({"overview/topic_summary"})

    MAP_PROMPT = "...extract per-section content from THIS part; {section_spec}..."
    REDUCE_PROMPT = "...merge fragments for {section}, keep under {max_chars}..."
    SUMMARY_PROMPT = "...write a faithful overview grounded only in these sections..."

    def prompt_context(self, meta: dict[str, Any]) -> dict[str, Any]:
        return {"filename": meta.get("filename", "unknown")}  # feeds {filename}

    async def summarize(self, sections: dict[str, str], meta: dict[str, Any]) -> dict[str, str]:
        compiled = "\n\n".join(f"## {n}\n{b}" for n, b in sections.items())
        resp = await self.call_model(self.SUMMARY_PROMPT, compiled[: self.reduce_input_chars])
        return {"overview/topic_summary": str(resp.get("summary", "")).strip()}

    def post_process(self, sections: dict[str, str], meta: dict[str, Any]) -> dict[str, dict[str, Any]]:
        # Deterministic coverage — computed from which sections actually filled,
        # never asked of the model. Can't hallucinate, can't dead-letter.
        filled = [n for n, body in sections.items() if body.strip()]
        return {"metadata.json": {"sections_filled": len(filled)}}
```

The **deterministic-coverage** pattern: `post_process` derives JSON artifacts
(coverage flags, metadata) from *which sections got real content*, rather than
asking the model "what did you cover?" A computed flag
can't be hallucinated and can't dead-letter on a partial document. Every other
knob (`chunk_chars`, `reduce_input_chars`, the `reduce()` and `prompt_context()`
seams) is documented on the `MapReduceExtractor` class itself — see the API
reference and the class docstring.

**Parallel map fan-out (`map_concurrency`).** The MAP phase makes one model call
per `chunk_chars` window, and those calls are independent — a ~840K-char statute
is ~9 windows. By default they run **one at a time** (`map_concurrency = 1`).
Raise the knob to map several windows at once, bounded by a semaphore:

```python
class MyExtractor(MapReduceExtractor):
    schema = ArtifactSchema.from_yaml("schema.yaml")
    model = "anthropic:claude-sonnet-4-6"
    chunk_chars = 100_000
    map_concurrency = 4   # up to 4 map calls in flight for one document
```

What it changes and what it doesn't:

- **Latency, not tokens.** The same windows are sent either way, so `tokens_in` /
  `cost_usd` are identical to the sequential run — you only cut wall-clock, toward
  `1/N` bounded by the slowest window (and your provider's rate limit). If tokens
  drop between runs it's the [map cache](#caching-ingestion) hitting, not
  concurrency.
- **Order-stable output.** Fragments are collected by window index, not
  completion order, so the compiled artifact is byte-for-byte the same as at
  `map_concurrency = 1`.
- **Failure semantics.** On a chunk error, in-flight windows finish and cache
  their results (so a re-run reuses them), windows not yet started are skipped,
  and the first error by window index is raised. At `map_concurrency = 1` the map
  still fails fast on the first error, exactly as before.

It's an extractor `ClassVar`, deliberately not a `reigner.yaml` field — same as
the other map-reduce knobs. This is distinct from the pipeline's `--concurrency`
(worker semaphore across *documents*); `map_concurrency` parallelizes *within one
document's* map phase, so the two compose (N documents × M windows).

#### Caching ingestion

Two independent caches avoid re-paying for extraction. They key on different
things.

**Document-level skip (always on).** Before running a source, the pipeline
compares a `cache_key` (`source_hash : schema_version : prompt_hash`) against the
entity's existing `extraction_meta.json`. Match → skip the whole document;
mismatch → re-extract it. For `MapReduceExtractor`, `prompt_hash` covers both the
map and reduce prompts. Use case: add 3 docs to a 500-doc corpus, re-run
`ingest`, only the 3 new ones compile.

**Chunk-level map cache (opt-in, `MapReduceExtractor` only).** Each chunk's map
result is saved under `sha256(chunk + rendered_map_prompt + schema.version)` —
the reduce prompt is excluded from the key. Off by default; enable by setting
`map_cache_dir`:

```python
from pathlib import Path

class MyExtractor(MapReduceExtractor):
    schema = ArtifactSchema.from_yaml("schema.yaml")
    model = "anthropic:claude-sonnet-4-6"
    map_cache_dir = Path("./.reigner/ingest-cache")   # enables the cache
```

Use cases:

- **Iterating on the reduce prompt.** Editing `REDUCE_PROMPT` changes the
  document-level key (forcing a re-run) but not the map key — so every chunk
  hits the cache and only the reduce calls re-pay. The larger the document (a
  ~840K-char statute maps in ~9 chunks), the more it saves.
- **Failure recovery.** Each chunk is cached as soon as its map call succeeds —
  including in-flight windows when another fails under
  [`map_concurrency`](#large--non-uniform-corpora) fan-out. A doc that
  dead-letters partway through reuses the already-mapped chunks on the re-run.

How they compose — the first cache decides *whether a document runs*, the second
*whether each map call inside it costs money*:

| Changed | Document skip | Map cache | Effect |
|---|---|---|---|
| Nothing | skip | not consulted | nothing runs |
| Reduce prompt | re-run | hits | reduce re-pays, map free |
| Map prompt / `schema.version` | re-run | misses | full re-extract |
| Reduce-side code (`summarize`, `post_process`, `reduce`) | skip | not consulted | doc skipped |

The last row is a footgun: the document key covers source + schema + prompts, not
your Python. Editing `reduce()` or `post_process()` and re-running skips the doc.
Force a re-run (delete the entity's `extraction_meta.json`) to pick up new
reduce-side code.

No eviction: when inputs change the key changes, so stale `<key>.json` files are
never read again (safe to `rm -rf`). A hit skips `call_model`, so `tokens_in` /
`cost_usd` count only the calls actually made.

**Scanned / image PDFs.** The default `raw_to_text` (PyMuPDF) is **text-only
in v0** — a scanned PDF with no text layer yields near-empty text, and *no*
extraction strategy can recover content from text that isn't there (map-reduce
just loops over nothing). Spot one by comparing page count to extracted length:
a high page count with near-zero characters means there's no text layer. The fix
is upstream OCR, or detect-and-park (move it out of `library/raw/` until OCR is
available). Multimodal extraction for scanned and image documents is tracked in
[#87](https://github.com/Construct-Lab/reigner/issues/87); see SPEC §8.5 for the
boundary.

### 3.3 Chat with your agent — `reigner chat`

`chat` builds the harness from `reigner.yaml`, auto-loads your project `.env`,
and opens a REPL — or runs one-shot with `--print`. It needs a model key.

**Interactive REPL:**

```console
$ reigner chat
› What does Orbit cost?
# representative output
  Retrieving…
  ✓ Retrieved  2 calls · 6.1k tok · $0.004 · 1.8s   /expand

  Sources
    [1] faq.md  section=pricing

  ╭─ Answer ──────────────────────────────────────╮
  │                                                │
  │  Orbit is $8 per user per month. [1]           │
  │                                                │
  ╰────────────────────────────────────────────────╯
›
```

The retrieval phase **collapses by default**: while the agent works, a
`Retrieving…` line shows; when the answer lands it folds to a one-line
`✓ Retrieved` recap, citations are pulled into a numbered **Sources** block, and
the answer renders in its own panel. Sources are referenced inline as `[1]` /
`[2]` rather than long parentheticals.

REPL controls:

| Key / command | Action |
|---|---|
| `Enter` | Submit a prompt — or, while a run is in flight, **queue it as your next question** (runs as its own turn after the current answer). |
| `Alt+Enter` (or `Esc` then `Enter`) | **Steer** the in-flight run: fold the typed text into the *current* answer at the loop's next boundary. |
| `/verbose` | Toggle verbose rendering: on = each tool call streams one self-describing line as it finishes; off = retrieval collapses to the recap. Also the `--verbose` / `-v` flag at launch. |
| `/expand` | Reprint the **last** turn's per-call tool detail below the recap (scrollback can't fold in place, so it reprints rather than un-collapsing). |
| `Ctrl+C` | Cancel the current run. |
| `/exit`, `/quit`, `Ctrl+D` | Quit the REPL. |

The input box wraps and grows downward as you type, so a long question stays
fully visible instead of scrolling off the right edge; **Enter** still submits.

The prompt stays live while a run streams, so there are two distinct mid-run
actions. **Enter** is type-ahead: your next question waits in line and runs as
its own turn once the current answer lands (like queuing a follow-up in Claude
Code / ChatGPT). **Alt+Enter** — or **Esc then Enter**, which works on terminals
without Option-as-Meta — *steers* the running answer instead, folding your text
into the current run as a user turn at its next iteration boundary.

> Neither action **preempts** the in-flight model call — there is deliberately
> no mid-turn interrupt for a bounded retrieval agent. Real-time
> interrupt-preemption stays parked under
> [#48](https://github.com/Construct-Lab/reigner/issues/48).

#### Reading the recap — tokens & run cost

The `✓ Retrieved` line reports, in order: the number of tool calls, how many
were truncated (if any), the **per-run token total**, the **run cost**, and
wall-clock elapsed.

- **Tokens** are accumulated across *every* model call in the turn, not just the
  final one — a multi-call retrieval turn shows the whole turn's tokens.
- **Cost** (`$0.004` above) is computed locally: provider APIs return token
  counts, never dollars, so Reigner prices the accumulated usage against a
  static per-model rate table (`reigner/pricing.py`), summing fresh input,
  output, and cache read/write at their distinct rates. It's rendered in gold —
  the same accent as citations — because it's a headline number.

The table ships rates for the current **Claude** (Opus 4.8/4.7, Sonnet 5/4.6,
Haiku 4.5, Fable 5), **OpenAI** (GPT-5.5), and **Gemini 3** (Pro, Flash) models.
For a model **not** in the table the cost figure is **omitted** (never guessed) —
the token count still shows. Rates are a hand-maintained snapshot; re-verify them
against provider pricing on model or price changes.

> Cost is surfaced in the interactive REPL recap today. Wiring it into the
> session `meta.json` totals (SPEC §11.1) and the `eval` `latency_cost` line
> ([Section 3.8](#38-evaluate-your-agent--reigner-eval)) is a planned follow-up.

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

model: openai:gpt-5.5  (temp=0.2)
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

**`role`** — prints the composed ROLE: the `REIGNER.md` the agent will load, its
resolved path, and the **skill menu** (each configured skill's name +
one-line description). Skill *bodies* aren't shown — they load on demand at run
time (see [Section 3.9](#39-skills--on-demand-instruction-modules)).

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

### 3.5 Sessions: list / show / tree / fork / replay — `reigner session`

Sessions are durable JSONL logs under `./.reigner/sessions/`, written
automatically by every `chat` run. They're **forkable and replayable** — the
foundation for A/B/C comparison of `REIGNER.md`/model/tool variants.

The `reigner session` command exposes the seven session operations. Every
`<id>` argument accepts an **unambiguous prefix** (`a1b2` resolves to
`a1b2c3d4…` when exactly one session matches), so you rarely type a full id:

```bash
reigner session list                       # table of every session (+ --json)
reigner session show a1b2                  # one session's rounds + citations (+ --json)
reigner session tree a1b2                  # the fork lineage, queried node marked (+ --json)
reigner session fork a1b2 --at-turn 2      # branch a child at round 2 (no model call)
reigner session replay a1b2 --at-turn 2    # re-run round 2 live (spends tokens)
reigner session replay a1b2 --with-role ./ALT.md   # ...against a different ROLE
reigner session export a1b2 --to out.jsonl # portable single-file export (+ sidecar meta)
reigner session import out.jsonl           # read an exported session back in
```

`session show <id>` is also reachable as `reigner inspect session <id>` — one
implementation, discoverable from either verb. The read commands (`list`,
`show`, `tree`) touch only the store on disk; only `replay` calls the model.

#### Fork — branch a conversation without spending tokens

`fork` snapshots a session up to round N and writes a new child whose history is
identical up to that point. No model call happens — it's pure bookkeeping on
disk — so it works offline and costs nothing. Use it to explore a different
follow-up question from a shared prefix:

```bash
# branch off after round 2, then ask the child something new:
reigner session fork 2536 --at-turn 2          # → ✓ forked 2536 → 0a8c666b…
reigner session show 0a8c                       # confirm the child carries rounds 1–2
reigner chat -c reigner.yaml --session 0a8c     # continue the branch live
```

Each fork shows up under the parent in `session tree`, so you can keep several
competing follow-ups side by side and compare their answers later.

#### Replay — re-run a recorded round live (spends tokens)

`replay` forks at round N, re-issues that round's recorded query, and runs it to
completion on the child — leaving the original untouched and diff-able. This is
the only session command that calls the model, so it needs your API key in the
environment / `./.env` and bills against it:

```bash
# re-run round 1 against the configured ROLE:
reigner session replay 2536 --at-turn 1

# A/B the same round against a different ROLE without touching the original —
# point --with-role at an edited copy:
cp REIGNER.md ALT.md            # edit ALT.md, then:
reigner session replay 2536 --at-turn 1 --with-role ALT.md
```

`--at-turn` defaults to the last round when omitted. Every replay creates a new
child you can then `show` / `tree` against the original, so iterating on a ROLE
becomes: edit, replay `--with-role`, diff, repeat.

The same capability is available from the Python API. Forking and replay are
methods on a `Session`; listing and lineage live on `SessionStore` and the
`tree` helpers:

```python
from reigner.harness.agent import Harness

harness = Harness.from_config("reigner.yaml")
session = harness.session()                 # new durable session
await session.run("What does Orbit cost?")  # the loop is async

# Branch off turn 2 into an independent, replayable child session.
branch = session.fork(at_turn=2)
await branch.run("...and how is data secured?")

# Replay round 2 live against the configured ROLE (this spends tokens).
restored = await session.replay(at_turn=2)
```

To replay against a *different* ROLE (what `--with-role` does on the CLI), build
a harness with the override role and load the session into it before replaying.
The override is a keyword arg on `from_config`; the same seam will later carry a
model override:

```python
from reigner.harness.agent import Harness, Session

alt = Harness.from_config("reigner.yaml", role_file="ALT.md")
restored = await Session.load(session.id, harness=alt).replay(at_turn=2)
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

Plugins hook into the loop without touching it. You list **dotted paths** under
`plugins:` in `reigner.yaml`, and each path resolves to one of two things:

- a **`Plugin` subclass** — the loader instantiates it with **no arguments**.
  Use this only for zero-arg plugins.
- a **pre-built `Plugin` instance** (`module:instance` form) — used as-is. This
  is what you must use for any plugin that takes constructor arguments, since
  the flat `plugins:` list has no per-plugin config block.

Anything else (a non-`Plugin` value, or a parameterized class referenced as a
bare path so the no-arg construction fails) is a loud `ConfigError` at startup.

#### Built-in plugins

Two ship in the box, one of each reference style:

- **`MetricsPlugin`** (`reigner.plugins.metrics`) — turns the loop into
  OpenTelemetry spans (one per *real* tool call — loop-managed pseudo-tools like
  `register_citation` are excluded — plus short spans for compaction, errors,
  oracle escalation, steering). Needs the `otel` extra **and** an OTel
  provider configured in *your* app — a missing `otel` dependency raises at
  construction rather than degrading to a silent no-op. Zero-arg, so reference
  the class directly. See the [Observability guide](observability.md).
- **`PiiRedactPlugin`** (`reigner.plugins.pii_redact`) — regex redaction of tool
  results (before they reach the model) **and** the final answer (before it
  reaches the user). No extra dependency. It requires `patterns`, so it **cannot**
  be a bare class path — build an instance and reference it.

`MetricsPlugin` wires as a bare class path; `PiiRedactPlugin` needs an instance:

```python
# myproject/observability.py
from reigner.plugins import PiiRedactPlugin

EMAIL_RE = r"[\w.+-]+@[\w-]+\.[\w.-]+"
redactor = PiiRedactPlugin(patterns=[r"\b\d{3}-\d{2}-\d{4}\b", EMAIL_RE])
```

```yaml
plugins:
  - reigner.plugins.metrics.MetricsPlugin   # zero-arg → class path
  - myproject.observability:redactor        # parameterized → module:instance
```

> Caveat: regex catches **structured** PII (SSNs, emails,
> card numbers) but not names or addresses. Treat `PiiRedactPlugin` as a
> backstop, not a guarantee.

##### Seeing `MetricsPlugin` spans (simple console exporter)

`MetricsPlugin` calls the **global** OpenTelemetry `TracerProvider`; until your
app sets one, spans hit a no-op tracer and vanish (by design — Reigner never
hijacks your telemetry). The fastest way to confirm it's working is a
`ConsoleSpanExporter`, which prints each span to stdout with no collector to
stand up. Install the SDK alongside the `otel` extra:

```bash
uv add 'reigner[otel]' opentelemetry-sdk
```

Then configure the provider **once, at your app's startup** (before the harness
runs):

```python
# myproject/tracing.py — import this early, e.g. at the top of your entrypoint
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)
```

With that provider live and `MetricsPlugin` wired, each tool call prints a span:

```text
# representative output
{
    "name": "reigner.tool.bm25_search",
    "attributes": {
        "reigner.session_id": "01J...",
        "reigner.tool": "bm25_search",
        "reigner.truncated": false,
        "reigner.cached": false
    },
    ...
}
```

`SimpleSpanProcessor` + `ConsoleSpanExporter` is for local sanity checks — it
exports synchronously and is noisy. For real backends (Langfuse, Tempo,
Honeycomb, Jaeger, …) swap in a `BatchSpanProcessor` with an OTLP exporter; the
[Observability guide](observability.md) has that production setup, plus the
`opentelemetry-instrument` env-var alternative.

#### Writing a custom plugin

Subclass `Plugin` and override only the hooks you care about — every hook
defaults to a safe no-op, so an audit logger is two methods:

```python
# myproject/plugins.py
import logging

from reigner.plugins import Plugin

log = logging.getLogger("myproject.audit")


class AuditLogPlugin(Plugin):
    name = "audit_log"

    async def before_tool_call(self, call, state):
        # transform hook — you MUST return a (possibly rewritten) call
        log.info("tool=%s session=%s args=%s", call.name, state.session_id, call.args)
        return call

    async def on_error(self, error, state):
        # observe hook — side effect only, returns None
        log.warning("run error (recoverable=%s): %s", error.recoverable, error.error)
```

Zero-arg, so wire it by class path:

```yaml
plugins:
  - myproject.plugins.AuditLogPlugin
```

The seven hooks split into two kinds, and the distinction matters for error
handling:

| Hook | Kind | Fires when | On raise |
|---|---|---|---|
| `before_tool_call` | transform | before a tool runs | **aborts the run** |
| `after_tool_call` | transform | after a tool result is bounded/truncated | **aborts the run** |
| `on_final_answer` | transform | before the answer is emitted | **aborts the run** |
| `on_compaction` | observe | a compaction tier fires | logged; next plugin runs |
| `on_error` | observe | a terminal error is about to emit | logged; next plugin runs |
| `on_oracle_escalation` | observe | a single-turn oracle escalation is armed | logged; next plugin runs |
| `on_steering` | observe | a queued steering message is accepted | logged; next plugin runs |

**Transform** hooks return a value that flows on through the loop (return the
input unchanged for a no-op); a raised exception is fatal. **Observe** hooks
return `None` and are isolated — a raise is logged and the next plugin still
runs. Plugins compose in list order, folding each transform's output into the
next.

---

### 3.8 Evaluate your agent — `reigner eval`

`reigner eval` runs an eval suite against your configured harness and prints a
markdown scorecard. Cases live in `eval/cases.yaml` (one query plus expectations);
checks come from `--check` flags, else `eval.checks` in `reigner.yaml`, else every
registered check.

```bash
reigner eval                          # all cases, all checks → scorecard
reigner eval --case apple_rnd_2024    # one case (repeatable)
reigner eval --check faithfulness     # one check (repeatable)
reigner eval --profile read_only      # full | read_only | eval (default: eval)
reigner eval --json                   # structured JSON instead of the scorecard
reigner eval --report                 # detailed per-case markdown (below)
```

A case is one query with optional expectations:

```yaml
# eval/cases.yaml
cases:
  - id: apple_rnd_2024
    query: "What were Apple's R&D expenses in 2024?"
    expected_citations:
      - "AAPL/2024/metrics.json#field=research_and_development"
    forbidden_phrases: ["I think", "approximately"]
    expected_clarification: false
    max_tokens: 20000          # optional latency_cost budget
    max_seconds: 30            # optional latency_cost budget
```

The scorecard (representative — needs a model):

```
## Eval results — 2026-05-06

| Case | faithfulness | repeated_calls | entity_resolution | coverage | latency_cost |
|---|---|---|---|---|---|
| apple_rnd_2024 | ✓ | ✓ | n/a | ✓ | ✓ (8.1k tok · 1.2s) |
| ambiguous_revenue | n/a | ✓ | ✓ (clarified) | n/a | ✓ (0 tok · 0.4s) |

2 cases · 2 passed · 0 failed
```

Cases run sequentially — each a full agent loop — so while the suite runs it
prints a `Running N eval case(s)…` banner and a per-case `✓`/`✗` tick **to
stderr** as each finishes. That progress is only a liveness signal: the scorecard
(and `--json` / `--report`) still goes to stdout unchanged, so piping and
redirects are unaffected.

**The five built-in checks** (all deterministic — no model calls; `na` = inapplicable):

| Check | Passes when |
|---|---|
| `faithfulness` | every numeric claim in the answer maps to a registered citation |
| `repeated_calls` | no identical `(tool, args)` call was issued twice |
| `entity_resolution` | an ambiguous case (`expected_clarification: true`) clarified instead of guessing |
| `coverage` | every `expected_citations` source was retrieved via a tool call |
| `latency_cost` | within `max_tokens` / `max_seconds` if set (else report-only) |

Two **intrinsic** checks always run alongside them: `forbidden_phrases` and
`expected_clarification`.

`--report` adds a per-case breakdown after the scorecard — the query, the agent's
response, the ordered tool-call trace, registered citations, cost, and each check's
verdict — useful for seeing *why* a case passed or failed.

**Exit codes:** `0` all cases passed · `1` some case failed · `2` usage error
(missing config/cases, unknown `--case`/`--check`, bad `--profile`). Usage errors
are caught *before* the harness is built, so a typo never costs a model call.

> **Profile note:** the default `eval` profile strips `request_clarification` for
> determinism, so an `expected_clarification: true` case can't clarify under it —
> run those with `--profile read_only`.

**How to test:** `reigner eval --case <id> --profile read_only` against an ingested
project, or the deterministic check logic directly via `pytest tests/eval/`.

---

### 3.9 Skills — on-demand instruction modules

A **skill** is a block of instructions the model pulls into context *only when
it needs it*. Your `REIGNER.md` is loaded in full at every turn — it's the right
home for rules that must **always** apply. A skill is the opposite: deep,
situational guidance that would bloat every prompt if it were always present, so
it's disclosed in two levels.

- **Level 1 — the menu (always present, cached).** At session start, each
  configured skill contributes one line — its `name` and a one-line
  `description` — composed into the stable ROLE. This is the model's cue that
  the skill exists. It's a handful of tokens and it lives in the cached prompt
  prefix, so it costs almost nothing.
- **Level 2 — the body (loaded on demand).** When a question makes a skill
  relevant, the model calls the `load_skill` tool; the skill's full
  `instructions` come back as a tool result and land in the conversation
  history. The stable ROLE is never rewritten, so the prompt cache keeps hitting
  on every adapter — the only cost is one turn of the body's tokens.

This is progressive disclosure, and it's uniform: there is **no "always-on"
skill tier**. Anything that must always hold goes in `REIGNER.md` (which is the
system prompt); a skill deepens a rule, it doesn't enforce one on its own.

#### Why skills

- **Keep the ROLE lean and the cache warm.** A 400-line procedure playbook in
  `REIGNER.md` is paid on every turn of every question. As a skill it's paid
  only on the questions that invoke it.
- **User-extensible.** The edge is that *you* write skills. A `role.skills:`
  entry is either a **bundled name** or a **dotted path** to your own `Skill`
  subclass — resolved against the project root, exactly like `tools.custom` and
  `plugins`.
- **Faithful across sessions.** `load_skill` is an ordinary tool call, so it's
  recorded in the session log. `reigner session` resume/fork/replay replays the
  *exact body the model saw* — even if you later remove the skill from config.

#### Bundled skills

Four ship with Reigner. Reference any by **bare name**:

| Name | Loads when the model needs to… | Requires |
|---|---|---|
| `citation_strict` | refuse a numeric claim without a registered citation | `register_citation` |
| `targeted_retrieval` | narrow with the `get_json_field → grep → read` grammar before reading | — |
| `clarify_when_ambiguous` | ask a clarifying question instead of guessing | `request_clarification` |
| `scratchpad_discipline` | persist a hard-won fact with `save_note` so compaction can't lose it | `save_note` |

The `Requires` column is each skill's `tools_required` — validated against the
wired tool registry at harness-build time, so a skill can't reference a tool
your project never configured (you get a `ConfigError`, not a silent no-op).

> Note these are *Reigner skills*, not Claude's "Skills" feature — same word,
> different concept.

#### Enabling skills

List them under `role.skills:` — bundled names and your own dotted paths mix
freely:

```yaml
role:
  file: REIGNER.md
  skills:
    - citation_strict          # bundled, by bare name
    - house.style:HouseStyle   # your own, by dotted path (module:Class)
```

`inspect role` shows the composed menu (offline, no model):

```console
$ reigner inspect role
file:   /path/to/mydocs/REIGNER.md
────────────────────────────────────────
# Identity
You answer questions about the Orbit product from compiled docs.


── Active skills (menu) ─────────────────
citation_strict  Refuse to make numeric claims without a registered citation.
house_style      Answer in the Orbit house voice: lead with the number, then one
sentence of why.

2 skill(s) loaded on demand via load_skill(name). Bodies are injected into
history when invoked — not shown here.
```

When at least one skill is configured, a `load_skill` tool is registered (it's
absent otherwise); you'll see it in `reigner inspect tools`.

#### Writing your own skill

Subclass `Skill` and set four class attributes. Put it anywhere importable from
the project root — a `skills/` package alongside `extractors/` is the natural
spot:

```python
# skills/house.py  (referenced as `skills.house:HouseStyle`)
from reigner.skills import Skill


class HouseStyle(Skill):
    """Answer in the Orbit house voice."""

    name = "house_style"                 # what the model passes to load_skill(name=...)
    description = (                       # the Level-1 menu line — make it a crisp trigger
        "Answer in the Orbit house voice: lead with the number, then one "
        "sentence of why."
    )
    tools_required = []                   # tool names the instructions assume (validated at build)
    instructions = """
    Lead with the concrete figure the user asked for. Follow with exactly one
    sentence of context. No hedging words ("roughly", "I think"). If a number
    isn't in the retrieved sources, say so rather than estimating.
    """                                   # the Level-2 body, revealed on load
```

`description` is the model's only cue for *when* to load the skill, so phrase it
as a trigger ("Answer in the house voice…"), not a title ("House voice"). The
`instructions` body is dedented and stripped automatically, so a triple-quoted
indented literal reads cleanly. An `examples` list attribute is also available
(carried, not composed into the body in v0). Keep bodies concise — very long
bodies are subject to the same per-tool truncation as any tool result
(`settings.max_tool_result_chars`).

#### Adding and removing skills flexibly

Skills are just a list — add, reorder, or drop entries and re-run. Two things to
know:

- **To disable all skills, use `skills: []`** — an explicit empty list. A bare
  `skills:` with every entry commented out parses as `null`, which fails the
  "must be a list" check:

  ```yaml
  # ✗ fails: "role.skills: Input should be a valid list"
  role:
    skills:
    #  - citation_strict

  # ✓ valid: no skills
  role:
    skills: []
    #  - citation_strict   # keep options as comments below the empty list
  ```

- **Removing a skill is safe for old sessions.** Because a loaded body was
  recorded in the session log, resuming or replaying a past session still
  reproduces it verbatim — dropping the skill from `role.skills` only affects
  *new* turns, which no longer see it in the menu.

#### What it looks like at run time

Ask two questions back to back and compare the traces in `reigner chat`:

1. *"What does Orbit cost?"* — answered directly; no skill loaded.
2. *"Give me the pricing in our house voice, leading with the number."* — the
   model calls `load_skill(name="house_style")` first (visible as a tool call in
   `--json` / `--verbose`), its body enters history, and the answer follows the
   method.

Question 1 pays nothing for a skill it doesn't need; question 2 pulls the guidance
in exactly when it applies.

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
  name: gpt-5.5
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
  skills: []                 # on-demand skill modules — bundled names or dotted paths (§3.9)

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

#### 4.1 Full `reigner.yaml` reference

The block above is what the **blank scaffold** ships (most of `tools:` commented
out). Below is the **exhaustive menu** — every key the schema accepts, fully
uncommented, with each line annotated `default · type · constraint`. The loader
uses `extra="forbid"` *everywhere*, so any key not listed here — including a
typo — fails loudly at load rather than being silently ignored.

```yaml
name: my_agent              # required · str
version: 0.1.0              # str · default "0.1.0"

model:                      # required — the main-loop LLM
  provider: openai          # openai | anthropic | gemini
  name: gpt-5.5              # str, non-empty
  temperature: 0.2          # float · default 0.2

oracle:                     # optional · single-turn escalation (SPEC §5.5)
  provider: anthropic       # openai | anthropic | gemini
  model: claude-opus-4-7    # NOTE: key is `model`, not `name` (asymmetric with model:)

settings:                   # all optional — these defaults are the source of truth
  max_iterations: 25            # int>0 · default 25 · loop iteration cap
  context_budget_tokens: 100000 # int>0 · default 100000
  max_tool_result_chars: 4000   # int>0 · default 4000 · global tool-result cap
  tool_result_char_limits:      # dict[str,int] · default {} · per-tool overrides, each >0
    bm25_search: 8000
  nudge_interval: 3             # int>0 · default 3 · turns between progress nudges
  max_consecutive_errors: 3     # int>0 · default 3 · abort after N back-to-back errors
  max_session_notes: 20         # int>0 · default 20 · save_note ring-buffer size
  history_keep_recent: 3        # int>0 · default 3 · turns kept verbatim on compaction
  compaction_thresholds: [0.80, 0.90, 0.95]  # 3 floats in (0,1), strictly increasing
  parallel_reads: true          # bool · default true · coalesce parallel read tools
  timeout_seconds: 120          # int>0 · default 120 · per model-call timeout

role:
  file: REIGNER.md          # str · default "REIGNER.md" · the instruction file
  skills: []                # list[str] · default [] · bundled names | dotted paths → Skill subclasses (§3.9)
  # cascade: ...            # ✗ HARD-REJECTED at load (SPEC §9) — there is no runtime cascade

tools:                      # every sub-block optional; omit one to leave that surface unwired
  artifacts:
    root: library/artifacts
    schema: ./schema.yaml   # NOTE: the YAML key is `schema` (aliased to schema_path internally)
  search:
    type: bm25              # str · default "bm25" (only bm25 ships today)
    index_path: search-index/documents.json
  fs:                       # optional read-only filesystem tool · EXACTLY ONE of root|roots
    root: .                 # single sandbox dir the agent may see, resolved against the config
    # roots:                # OR multi-root: name → repo path (the code_navigator recipe, §3.1.2)
    #   backend: ../api     #   each name becomes a top-level dir; names match [A-Za-z0-9_-]+
    #   frontend: ~/code/web  # paths may be relative (to config), absolute, or ~/…
    write_enabled: false    # bool · default false — read-only is the safe default
  custom: []                # list[dotted-path] · default [] · extra @tool surfaces to register

sessions:
  store_path: ./.reigner/sessions  # str · default "./.reigner/sessions"
  auto_save: true                  # bool · default true

plugins: []                 # list[dotted-path] · default [] · see Section 3.7

eval:                       # optional · used by `reigner eval` (§3.8)
  cases: eval/cases.yaml    # str · default "eval/cases.yaml"
  checks: []                # list[str] · names to run; [] = all registered
                            #   (faithfulness, repeated_calls, entity_resolution,
                            #    coverage, latency_cost). --check overrides this.
```

Three footguns the schema enforces:

- **`oracle.model` vs `model.name`** — the main model block names the model under
  `name:`, but the oracle block uses `model:`. They are deliberately asymmetric;
  using `name:` under `oracle:` is a forbidden-key error.
- **`tools.artifacts.schema`** — the YAML key is `schema` (it maps to
  `schema_path` inside the loader). Write `schema:`, not `schema_path:`.
- **Closed provider set + forbidden extras** — `provider` must be one of
  `openai`, `anthropic`, `gemini`, and *every* block rejects unknown keys, so a
  misspelled setting surfaces immediately at `reigner inspect config` or any
  command that loads the config.

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
- `./.reigner/ingest-cache/` — optional chunk-level map cache for
  `MapReduceExtractor`, written only when you set `map_cache_dir` (off by
  default). See [Caching ingestion](#caching-ingestion).

---

## 5. Known gaps / not-yet-wired

Short list of what the scaffolding promises but doesn't do yet. Each links its
tracking issue.

- **eval Python API** — the eval suite is also usable directly from Python
  (`EvalSuite.from_yaml(...).run(harness, checks=[...])` → `render_scorecard` /
  `render_report`); see [Section 3.8](#38-evaluate-your-agent--reigner-eval) for
  the CLI. Each case runs in a fresh session and never aborts the suite.
- **`reigner init --recipe`** — ✅ ships **both** SPEC recipes: `document_qa`
  ([Section 3.1.1](#311-the-document_qa-recipe)) and `code_navigator`
  ([Section 3.1.2](#312-the-code_navigator-recipe-multi-repo)).
- **`reigner serve --mcp`** — ⏳ exits with a "not yet implemented" message
  ([Section 3.6](#36-serve-the-agent--reigner-serve)).
- **Real-time steering interrupt-preemption** — ⏳ deliberately not built.
  Mid-run interaction works end-to-end (the prompt stays live during a run):
  **Enter** type-aheads your next question, **Alt+Enter** steers the current
  answer. Neither aborts the in-flight model call — preemption is parked as a
  conscious non-goal for a bounded retrieval agent
  ([#48](https://github.com/Construct-Lab/reigner/issues/48)).

This doc is a hand-verified snapshot — when a track lands, its row here and in
[Section 2](#2-feature-status) should be updated to match.
