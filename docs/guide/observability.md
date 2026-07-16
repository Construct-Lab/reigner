# Observability

`MetricsPlugin` turns the agent loop into OpenTelemetry spans: one span per *real*
tool call (tagged with the tool name, session id, and whether the result was truncated
or cached), plus marker spans for compaction, errors, oracle escalations, and steering.
Loop-managed pseudo-tools (e.g. `register_citation`, `save_note`) emit no tool span;
`escalate_to_oracle` and `stop` instead surface through their dedicated marker hooks.

Reigner ships **only `opentelemetry-api`** — the interface, not an exporter. The plugin
calls the global OpenTelemetry `TracerProvider`, so spans only go somewhere once **your
application** configures one. Add the plugin without a provider and spans hit a no-op
tracer and are silently discarded — by design, Reigner never hijacks your telemetry setup.

## 1. Install the API plus an SDK and exporter

The SDK and exporter are your choice, not part of the extra:

```bash
uv add 'reigner[otel]' opentelemetry-sdk opentelemetry-exporter-otlp
```

## 2. Configure OpenTelemetry once, at app startup

Setting the global provider is what makes spans real; every span emitted through the OTel
API in the process then flows to your exporter (Langfuse, Tempo, Honeycomb, Jaeger, …):

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

## 3. Add the plugin to `reigner.yaml`

It is zero-arg, so a bare class path resolves:

```yaml
plugins:
  - reigner.plugins.metrics.MetricsPlugin
```

The plugin is instantiated when the harness loads; if `[otel]` is not installed, that is
where a clear `ImportError` is raised.

## What is not emitted yet

Token counts, cost, and per-turn model latency. Those live on the model-adapter calls,
which don't pass through the tool-call hooks, so they wait on usage tracking landing in
`AgentState`.

## Redacting PII

For redacting PII before it reaches the model or the final answer, see
`reigner.plugins.PiiRedactPlugin`.
