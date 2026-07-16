# Observability

`MetricsPlugin` turns the agent loop into OpenTelemetry spans: one span per *real*
tool call (tagged with the tool name, session id, and whether the result was truncated
or cached), plus marker spans for compaction, errors, oracle escalations, and steering.
Loop-managed pseudo-tools (e.g. `register_citation`, `save_note`) emit no tool span;
`escalate_to_oracle` and `stop` instead surface through their dedicated marker hooks.

Reigner ships **only `opentelemetry-api`** — the interface, not an exporter. The plugin
calls the global OpenTelemetry `TracerProvider`, so spans only go somewhere once a real
provider is configured in the process. Add the plugin without one and spans hit a no-op
tracer and are silently discarded — by design, Reigner never hijacks your telemetry setup.

## 1. Install the API plus an SDK and exporter

The SDK and exporter are your choice, not part of the extra:

```bash
uv add 'reigner[otel]' opentelemetry-sdk opentelemetry-exporter-otlp
```

## 2. Wire the plugin — and a provider

Who sets the provider depends on who owns telemetry.

### Project-owned: a telemetry sidecar module (recommended)

For projects driven through the CLI (`chat`, `serve`, `eval`), let the project itself
own the wiring. Create a sidecar module at the project root:

```python
# otel.py — wires the provider, then exposes the plugin instance.
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from reigner.plugins.metrics import MetricsPlugin

provider = TracerProvider(resource=Resource.create({"service.name": "my-reigner-app"}))
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))  # endpoint/headers via env
trace.set_tracer_provider(provider)

metrics = MetricsPlugin()
```

and reference the instance instead of the bare class path:

```yaml
plugins:
  - otel:metrics
```

Loading the config imports the module, so the provider is set before the plugin is
constructed — the import side effect is the point. Reigner puts the project root on the
import path, so a root-level `otel.py` resolves regardless of where you run from.

Every surface that loads this config — `reigner chat`, `reigner serve`, `reigner eval`,
or your own `Harness.from_config(...)` — now exports spans identically, with no
per-surface setup. On exit the SDK's registered shutdown flushes the last batch, so
short CLI runs don't lose the tail.

!!! tip "Keep your tracked config untouched"
    If you are only experimenting, put the sidecar reference in a copy of the config
    (say `reigner.otel.yaml`) and load that — flipping plugins on and off in the
    tracked `reigner.yaml` churns your project file.

### App-owned: bare class path

If Reigner is embedded in an application that already configures OpenTelemetry, keep
the yaml to the bare class path — `MetricsPlugin` is zero-arg, so it resolves directly:

```yaml
plugins:
  - reigner.plugins.metrics.MetricsPlugin
```

and set the provider once at app startup, before the harness loads:

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

!!! warning "Short scripts must `force_flush()`"
    `BatchSpanProcessor` exports in the background. A script that builds its own
    provider and exits right after the run drops whatever is still buffered — call
    `provider.force_flush()` before exit. (Long-running servers don't need this;
    the batch timer catches up.)

Either way, the plugin is instantiated when the harness loads; if `[otel]` is not
installed, that is where a clear `ImportError` is raised.

## Worked example: OpenObserve

The full path end to end with the sidecar form and
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

The OTLP exporter picks up the standard environment variables, so nothing is
hardcoded in the sidecar:

```bash
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:5080/api/default/v1/traces
export OTEL_EXPORTER_OTLP_TRACES_HEADERS="Authorization=Basic $(printf 'root@example.com:Complexpass#123' | base64)"
```

### Add the sidecar and chat

Drop the `otel.py` sidecar from above into the project root, point `plugins:` at
`otel:metrics`, and run a normal session:

```bash
uv run reigner chat --print "What are the main concerns about the rule of law?"
```

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
