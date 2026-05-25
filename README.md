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

## Observability

`MetricsPlugin` turns the agent loop into OpenTelemetry spans: one span per tool
call (tagged with the tool name, session id, and whether the result was
truncated or cached), plus marker spans for compaction, errors, oracle
escalations, and steering.

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

## Development

```bash
uv sync --all-extras --group dev
uv run pre-commit install
uv run pytest
```

CI runs `ruff check`, `ruff format --check`, `mypy`, and `pytest` on every PR.
