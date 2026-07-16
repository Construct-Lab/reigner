<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/reigner-logo-dark.svg">
    <img alt="reigner" src="assets/reigner-logo-light.svg" width="360">
  </picture>
</p>

<p align="center"><strong>A single agent that answers from your compiled corpus — every claim cited.</strong></p>

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
uv add 'reigner[anthropic,ingestion]'      # model adapter + PDF/URL loaders

reigner init mydocs --recipe document_qa   # scaffold a project
# drop your PDFs/text into mydocs/, then:
cd mydocs
reigner ingest                             # compile documents into artifacts
reigner chat                               # ask questions, get cited answers
```

![reigner chat answering a question with per-claim citations](docs/assets/demo.gif)

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
