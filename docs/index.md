# Reigner

**A single agent that answers from your compiled corpus — every claim cited.**

Reigner is a toolkit for building **citation-faithful question-answering agents over a
knowledge corpus.** You compile your sources into bounded, schema-aware artifacts once,
then a single retrieval agent answers over them — every factual claim traced back to its
source. It is a library first: not a chat app, not a coding-agent harness, not a
multi-agent orchestrator.

![reigner chat answering a question with per-claim citations](assets/demo.gif)

## One core, three surfaces

You meet the same agent core — the harness, the artifact store, and a single
`REIGNER.md` instruction file — at three points in its lifecycle:

- **Build** — define a per-project agent as a library: a schema, `@tool`s, an extractor,
  a recipe, plugins. This is what you ship.
- **Test** — iterate from the CLI: [`ingest`](guide/usage.md), `chat`, then
  `session fork` / `replay` / `export` and `eval` to A/B/C variants of your `REIGNER.md`,
  tools, or model.
- **Ship** — serve the same agent over HTTP (FastAPI + SSE) so your apps consume it with
  no rewrite.

!!! note "MCP export is planned"
    `reigner serve --http` works today. `reigner serve --mcp` is scaffolded but not yet
    wired — it exits with a clear "not yet implemented" message. The "ship" surface is
    FastAPI/SSE for now.

## Where to go next

- **[Usage guide](guide/usage.md)** — hands-on, install → scaffold → ingest → chat, with
  a per-feature status flag on everything.
- **[Observability](guide/observability.md)** — turn the agent loop into OpenTelemetry spans.
- **[Design (spec)](design/spec.md)** — package layout, guardrails, API contracts, the
  event protocol, configuration schema.
- **[Principles](design/principles.md)** — the rationale behind each design decision.
- **[API reference](reference.md)** — the typed public API.

## Install

```bash
uv add 'reigner[anthropic,ingestion]'      # model adapter + PDF/URL loaders
```

Reigner ships a thin core; each capability is an opt-in extra — see the
[usage guide](guide/usage.md#install) for the full extras table.
