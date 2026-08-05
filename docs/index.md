# Reigner

**A harness for question-answering agents over your own documents — bounded context,
bounded cost, every claim cited.**

Point an agent at a pile of documents and it degrades the same way every time: context
fills up, cost climbs, and by the twentieth turn you can't tell which answers are grounded
in a source. The answering was never the hard part. The machinery around it was.

Reigner is that machinery — **a harness for citation-faithful question-answering agents
over a knowledge corpus.** A small, legible agent loop with explicit guardrails for context
and spend, plus the ingestion, tools, sessions and evals to aim it at your own documents.
First you *ingest* your sources — a one-time compile step that reads your raw documents
(PDF, text, HTML) and extracts the facts you care about into a structured store, its
*artifacts*. A single retrieval agent then answers questions over that store — never
touching your raw files at query time — with every factual claim traced back to its source.

It's a library, not a product: not a chat app, not a multi-agent orchestrator, and a
harness for *retrieval* agents rather than coding agents — Claude Code and Codex CLI have
that covered. Reach for Reigner when you want a Q&A agent shaped to *your* corpus and use
case: the instructions, the tools, the schema, the model are all yours to change. Within
that flexibility two things stay hard — citation-faithfulness is a testable property (the
eval fails uncited claims), and a cheap model handles the routine work so cost stays
bounded.

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
- **[Principles](design/principles.md)** — why Reigner exists and the rationale behind each design decision.
- **[API reference](reference.md)** — the typed public API.

## Install

```bash
uv add 'reigner[anthropic,ingestion]'      # model adapter + PDF/URL loaders
```

Reigner ships a thin core; each capability is an opt-in extra — see the
[usage guide](guide/usage.md#install) for the full extras table.
