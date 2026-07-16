<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/reigner-logo-dark.svg">
    <img alt="reigner" src="assets/reigner-logo-light.svg" width="360">
  </picture>
</p>

<p align="center"><strong>Single-agent, retrieval-shaped, citation-faithful agents over compiled knowledge.</strong></p>

[![PyPI](https://img.shields.io/pypi/v/reigner.svg)](https://pypi.org/project/reigner/)
[![Python](https://img.shields.io/pypi/pyversions/reigner.svg)](https://pypi.org/project/reigner/)
[![CI](https://github.com/Construct-Lab/reigner/actions/workflows/ci.yml/badge.svg)](https://github.com/Construct-Lab/reigner/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

📚 **Documentation:** https://construct-lab.github.io/reigner/

Reigner is a toolkit for building **citation-faithful question-answering agents over a knowledge corpus.**
You compile your sources into bounded, schema-aware artifacts once, then a single
retrieval agent answers over them — every factual claim traced back to its source.
It is a library first: not a chat app, not a coding-agent harness, not a multi-agent
orchestrator.

## One core, three surfaces

You meet the same agent core — the harness, the artifact store, and a single
`REIGNER.md` instruction file — at three points in its lifecycle:

- **Build** — define a per-project agent as a library: a schema, `@tool`s, an
  extractor, a recipe, plugins. This is what you ship.
- **Test** — iterate from the CLI: `ingest`, `chat`, then `session fork` / `replay` /
  `diff` and `eval` to A/B/C variants of your `REIGNER.md`, tools, or model.
- **Ship** — serve the same agent over HTTP (FastAPI + SSE) so your apps consume it
  with no rewrite. (MCP export is planned; see status below.)

## Features

- **Compiled artifacts** — ingestion compiles raw documents into a bounded,
  schema-aware store. The agent queries the compiled graph, never your raw files.
- **Bounded, self-describing tools** — every tool result reports `has_more`,
  `truncated`, and `available_keys`, so a finite-context model always knows whether
  it got everything.
- **Citations are first-class** — numeric and factual claims register a
  `CitationEvent` with provenance; the eval suite fails answers that make uncited claims.
- **Forkable sessions** — durable JSONL sessions on disk that you can fork and replay
  to compare variants without re-running from scratch.
- **One typed event protocol** — CLI, HTTP, and MCP all consume the same typed events.
- **Provider-agnostic** — Anthropic, OpenAI, and Gemini adapters behind one interface.

## Quickstart

```bash
uv add 'reigner[anthropic]'

reigner init mydocs --recipe document_qa   # scaffold a project
# drop your PDFs/text into mydocs/, then:
cd mydocs
reigner ingest                             # compile documents into artifacts
reigner chat                               # ask questions, get cited answers
```

The full walkthrough — every command with real output and a per-feature status flag —
is in the [usage guide](https://construct-lab.github.io/reigner/guide/usage/).

## Install

```bash
uv add reigner
```

Reigner ships a thin core; each capability is an opt-in extra:

| Extra | Purpose |
|---|---|
| `reigner[anthropic]` | Anthropic model adapter |
| `reigner[openai]` | OpenAI model adapter |
| `reigner[gemini]` | Gemini model adapter |
| `reigner[server]` | FastAPI HTTP server with SSE |
| `reigner[mcp]` | MCP server export (planned — not wired yet) |
| `reigner[ingestion]` | PDF/URL loaders for the ingestion pipeline |
| `reigner[otel]` | OpenTelemetry metrics plugin |
| `reigner[all]` | Everything above |

### License note

Reigner itself is MIT-licensed. The `[ingestion]` extra pulls in
[PyMuPDF](https://pymupdf.readthedocs.io/), which is **AGPL-3.0**. Downstream projects
that distribute or network-serve a closed-source product on top of `reigner[ingestion]`
must comply with AGPL or obtain a [PyMuPDF Pro](https://pymupdf.io/) commercial license.
To avoid the AGPL entirely, override `LLMExtractor.raw_to_text` with a
permissive-licensed loader of your choice.

## Learn more

`MetricsPlugin` turns the agent loop into OpenTelemetry spans: one span per
*real* tool call (tagged with the tool name, session id, and whether the result
was truncated or cached), plus marker spans for compaction, errors, oracle
escalations, and steering. Loop-managed pseudo-tools (e.g. `register_citation`,
`save_note`) emit no tool span; `escalate_to_oracle` and `stop` instead surface
through their dedicated marker hooks.

Reigner ships **only `opentelemetry-api`** — the interface, not an exporter. The
plugin calls the global OpenTelemetry `TracerProvider`, so spans only go
somewhere once **your application** configures one. Add the plugin without a
provider and spans hit a no-op tracer and are silently discarded — by design,
Reigner never hijacks your telemetry setup.

**1. Install the API plus an SDK and exporter** (the SDK/exporter are your
choice, not part of the extra):

```bash
uv add 'reigner[otel]' opentelemetry-sdk opentelemetry-exporter-otlp
```

**2. Configure OpenTelemetry once, at app startup.** Setting the global provider
is what makes spans real; every span emitted through the OTel API in the process
then flows to your exporter (Langfuse, Tempo, Honeycomb, Jaeger, …):

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="...")))
trace.set_tracer_provider(provider)
```

Or skip the Python and use `opentelemetry-instrument` with the standard
`OTEL_EXPORTER_OTLP_ENDPOINT` environment variables.

**3. Add the plugin to `reigner.yaml`** — it is zero-arg, so a bare class path
resolves:

```yaml
plugins:
  - reigner.plugins.metrics.MetricsPlugin
```

The plugin is instantiated when the harness loads; if `[otel]` is not installed,
that is where a clear `ImportError` is raised.

Not yet emitted: token counts, cost, and per-turn model latency. Those live on
the model-adapter calls, which don't pass through the tool-call hooks, so they
wait on usage tracking landing in `AgentState`.

For redacting PII before it reaches the model or the final answer, see
`reigner.plugins.PiiRedactPlugin`.
- **[Usage guide](https://construct-lab.github.io/reigner/guide/usage/)** — hands-on, install → scaffold → ingest → chat.
- **[Observability](https://construct-lab.github.io/reigner/guide/observability/)** — OpenTelemetry spans for the agent loop.
- **[Design (spec)](https://construct-lab.github.io/reigner/design/spec/)** — package layout, guardrails, API contracts, event protocol.
- **[Principles](https://construct-lab.github.io/reigner/design/principles/)** — the rationale behind each design decision.
- **[API reference](https://construct-lab.github.io/reigner/reference/)** — the typed public API.

## Development

```bash
uv sync --all-extras --group dev
uv run pre-commit install
uv run pytest
```

CI runs `ruff check`, `ruff format --check`, `mypy`, and `pytest` on every PR.

## License

MIT — see [LICENSE](LICENSE).
