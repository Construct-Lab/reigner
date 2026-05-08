# Reigner

Single-agent, retrieval-shaped, citation-faithful agents over compiled knowledge.

> Status: pre-implementation. See [`SPEC.md`](SPEC.md) for the v0 contract and
> [`PRINCIPLES.md`](PRINCIPLES.md) for design rationale.

## Install

```bash
uv add reigner
```

Optional extras (each track populates its own as features land):

| Extra | Purpose |
|---|---|
| `reigner[anthropic]` | Anthropic model adapter |
| `reigner[openai]` | OpenAI model adapter |
| `reigner[gemini]` | Gemini model adapter |
| `reigner[server]` | FastAPI HTTP server with SSE |
| `reigner[mcp]` | MCP server export |
| `reigner[ingestion]` | PDF/URL loaders for the ingestion pipeline |
| `reigner[otel]` | OpenTelemetry metrics plugin |
| `reigner[all]` | Everything above |

### License notes

Reigner itself is MIT-licensed. The `[ingestion]` extra pulls in
[PyMuPDF](https://pymupdf.readthedocs.io/), which is **AGPL-3.0**. Downstream
projects that distribute or network-serve a closed-source product on top of
`reigner[ingestion]` must comply with AGPL or obtain a
[PyMuPDF Pro](https://pymupdf.io/) commercial license. To avoid the AGPL
entirely, override `LLMExtractor.preprocess_pdf` with a permissive-licensed
loader of your choice.

## Development

```bash
uv sync --all-extras --group dev
uv run pre-commit install
uv run pytest
```

CI runs `ruff check`, `ruff format --check`, `mypy`, and `pytest` on every PR.
