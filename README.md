<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Construct-Lab/reigner/main/assets/reigner-logo-dark.svg">
    <img alt="reigner" src="https://raw.githubusercontent.com/Construct-Lab/reigner/main/assets/reigner-logo-light.svg" width="360">
  </picture>
</p>

<p align="center"><strong>A harness for question-answering agents over your own documents — bounded context, bounded cost, every claim cited.</strong></p>

[![PyPI](https://img.shields.io/pypi/v/reigner.svg)](https://pypi.org/project/reigner/)
[![Python](https://img.shields.io/pypi/pyversions/reigner.svg)](https://pypi.org/project/reigner/)
[![CI](https://github.com/Construct-Lab/reigner/actions/workflows/ci.yml/badge.svg)](https://github.com/Construct-Lab/reigner/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

📚 **Documentation:** https://construct-lab.github.io/reigner/

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

## One core, three surfaces

Reigner is a library: you write **one** agent and reach it three ways as it grows
from an idea to a running service. The agent is a small project folder — a
`REIGNER.md` of instructions, a schema, and your tools — and it stays the same
folder at every step.

- **Build** — Write your agent as code. `reigner init` scaffolds the project folder
  for you: the `REIGNER.md` instructions, a schema and extractor (how your documents
  become searchable), plus any `@tool`s or plugins you add. This folder *is* your agent.
- **Test** — Run it from your terminal. `ingest` compiles your documents, `chat` asks
  questions, and `session fork` / `replay` / `eval` let you A/B/C different instructions,
  tools, or models — so you tune without starting over.
- **Ship** — Serve it over HTTP. `serve` exposes that same folder through a FastAPI endpoint
  that streams over Server-Sent Events (SSE), so your apps consume it with no rewrite.
  (MCP — Model Context Protocol — export is planned; see status below.)

## Features

- **Compiled artifacts** — ingestion compiles raw documents into a bounded,
  schema-aware store. The agent queries the compiled graph, never your raw files.
- **Bounded, self-describing tools** — every tool result reports `has_more`,
  `truncated`, and `available_keys`, so a finite-context model always knows whether
  it got everything.
- **Citations are first-class** — numeric and factual claims register a
  `CitationEvent` with provenance; the eval suite fails answers that make uncited claims.
- **Oracle escalation** — a cheap default model runs the loop and calls
  `escalate_to_oracle` only when a question needs deeper reasoning; that single turn is
  served by a stronger model, then it reverts. You pay frontier prices for the hard steps,
  not the routine ones.
- **Context stays bounded under pressure** — a legible agent loop with numbered guardrails:
  pressure-driven history compaction, per-tool result truncation, and a scratchpad whose
  notes survive compaction — so long runs don't blow the context budget.
- **Parallel, cached reads** — read-only tool calls in a turn run concurrently and hit a
  per-session cache, cutting both latency and duplicate model-driven calls.
- **An eval battery** — score your agent against your own compiled corpus for faithfulness,
  coverage, and repeated-call efficiency; iterate on `REIGNER.md`, tools, or model with numbers.
- **Forkable sessions** — durable JSONL sessions on disk that you can fork and replay
  to compare variants without re-running from scratch.
- **Write your UI once** — the CLI, HTTP server, and MCP all emit the same typed events
  (tool calls, citations, status), so an interface, logger, or integration you build against
  one surface works unchanged against the others.
- **Provider-agnostic** — Anthropic, OpenAI, and Gemini adapters behind one interface.

## Quickstart

```bash
uv add 'reigner[anthropic,ingestion]'      # model adapter + PDF/URL loaders

reigner init mydocs --recipe document_qa   # scaffold a project
# drop your PDFs/text into mydocs/, then:
cd mydocs
reigner ingest                             # compile documents into artifacts
reigner chat                               # ask questions, get cited answers
```

![reigner chat answering a question with per-claim citations](https://raw.githubusercontent.com/Construct-Lab/reigner/main/docs/assets/demo.gif)

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

- **[Usage guide](https://construct-lab.github.io/reigner/guide/usage/)** — hands-on, install → scaffold → ingest → chat.
- **[Architecture](https://construct-lab.github.io/reigner/guide/architecture/)** — the harness: agent loop, oracle escalation, and the G1–G11 context guardrails.
- **[Observability](https://construct-lab.github.io/reigner/guide/observability/)** — OpenTelemetry spans for the agent loop.
- **[Principles](https://construct-lab.github.io/reigner/design/principles/)** — why Reigner exists and the rationale behind each design decision.
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
