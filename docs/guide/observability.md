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

!!! tip "Keep your tracked config untouched"
    If you are only experimenting, put the plugin in a copy of the config
    (say `reigner.otel.yaml`) and load that — flipping plugins on and off in the
    tracked `reigner.yaml` churns your project file.

## Worked example: OpenObserve

Steps 1–3 work with any OTLP backend. Here is the full path end to end with
[OpenObserve](https://openobserve.ai/) — a single container with a traces UI.

### Run the backend

```bash
docker run -d --name openobserve -p 5080:5080 \
  -e ZO_ROOT_USER_EMAIL=root@example.com \
  -e ZO_ROOT_USER_PASSWORD='Complexpass#123' \
  -v "$PWD/oo-data:/data" openobserve/openobserve:latest
```

The UI is at `http://localhost:5080`; OTLP HTTP trace ingest is
`/api/default/v1/traces` with Basic auth (base64 of `email:password`).

### Point the exporter at it

The OTLP exporter picks up the standard environment variables, so no endpoint needs to
be hardcoded:

```bash
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:5080/api/default/v1/traces
export OTEL_EXPORTER_OTLP_TRACES_HEADERS="Authorization=Basic $(printf 'root@example.com:Complexpass#123' | base64)"
```

### Run a session and flush

```python
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

provider = TracerProvider(resource=Resource.create({"service.name": "my-reigner-app"}))
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))  # endpoint/headers via env
trace.set_tracer_provider(provider)

from reigner.harness.agent import Harness

harness = Harness.from_config("reigner.otel.yaml")
session = harness.session()
await session.run("What are the main concerns about the rule of law?")

provider.force_flush()  # don't lose the tail batch
```

!!! warning "Short scripts must `force_flush()`"
    `BatchSpanProcessor` exports in the background. A script that exits right after the
    run drops whatever is still buffered — call `provider.force_flush()` before exit.
    (Long-running servers don't need this; the batch timer catches up.)

Then open the UI → **Traces** and filter on `service.name = my-reigner-app`.

!!! note "OpenObserve quirks"
    - **Blank columns are a display artifact.** Trace streams use a per-stream union
      schema, so attributes set only by some span types (e.g. `reigner.from_model` on
      oracle markers) render as empty columns on every other span. The data is there.
    - **Stream stats lag.** `doc_num` can read 0 right after ingest. If in doubt, query
      the search API directly (`POST /api/default/_search?type=traces` with SQL) rather
      than trusting the stats page.

## Span reference

| Span | Emitted when | Attributes |
|---|---|---|
| `reigner.tool.<name>` | each real tool call | `reigner.session_id`, `reigner.tool`, `reigner.truncated`, `reigner.cached` |
| `reigner.compaction` | context is compacted | `reigner.level` |
| `reigner.error` | an error event fires | `reigner.error`, `reigner.recoverable` |
| `reigner.oracle` | oracle escalation | `reigner.from_model`, `reigner.to_model` |
| `reigner.steering` | a steering event fires | `reigner.mode` |

## What is not emitted yet

- **A root span per run.** Spans are currently parentless, so one run shows up as N
  disconnected traces rather than one trace with children. A `reigner.run` root span is
  planned.
- **Token counts, cost, and per-turn model latency.** Usage lives on
  `final_answer.metadata.usage`, which doesn't pass through the tool-call hooks, so it
  never reaches telemetry yet. This will ride along with the root span.

## Redacting PII

For redacting PII before it reaches the model or the final answer, see
`reigner.plugins.PiiRedactPlugin`.
