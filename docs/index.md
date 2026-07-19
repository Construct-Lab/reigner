# Reigner

**A single agent that answers from your compiled corpus — every claim cited.**

Reigner is a toolkit for building **citation-faithful question-answering agents over a
knowledge corpus.** You compile your sources into bounded, schema-aware artifacts once,
then a single retrieval agent answers over them — every factual claim traced back to its
source. It is a library first: not a chat app, not a coding-agent harness, not a
multi-agent orchestrator.

![reigner chat answering a question with per-claim citations](assets/demo.gif)

## One core, three surfaces

Reigner is a library: you write **one** agent and reach it three ways as it grows
from an idea to a running service. The agent is a small project folder — a
`REIGNER.md` of instructions, a schema, and your tools — and it stays the same
folder at every step.

- **Build** — Write your agent as code. `reigner init` scaffolds the project folder
  for you: the `REIGNER.md` instructions, a schema and extractor (how your documents
  become searchable), plus any `@tool`s or plugins you add. This folder *is* your agent.
- **Test** — Run it from your terminal. [`ingest`](guide/usage.md) compiles your
  documents, `chat` asks questions, and `session fork` / `replay` / `export` / `eval`
  let you A/B/C different instructions, tools, or models — so you tune without starting
  over.
- **Ship** — Serve it over HTTP. `serve` exposes that same folder through a FastAPI + SSE
  endpoint, so your apps consume it with no rewrite.

!!! note "MCP export is planned"
    `reigner serve --http` works today. `reigner serve --mcp` is scaffolded but not yet
    wired — it exits with a clear "not yet implemented" message. The "ship" surface is
    FastAPI/SSE for now.

## Where to go next

- **[Usage guide](guide/usage.md)** — hands-on, install → scaffold → ingest → chat, with
  a per-feature status flag on everything.
- **[Architecture](guide/architecture.md)** — the harness: the agent loop, oracle
  escalation, and the G1–G11 context-management guardrails.
- **[Observability](guide/observability.md)** — turn the agent loop into OpenTelemetry spans.
- **[Principles](design/principles.md)** — the rationale behind each design decision.
- **[API reference](reference.md)** — the typed public API.

## Install

```bash
uv add 'reigner[anthropic,ingestion]'      # model adapter + PDF/URL loaders
```

Reigner ships a thin core; each capability is an opt-in extra — see the
[usage guide](guide/usage.md#install) for the full extras table.
