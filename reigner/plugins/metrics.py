"""Emit OpenTelemetry spans around the loop.

A bare-bones observe plugin — an integration *point*, not a telemetry product.
It opens one span per tool call and emits a short span for each observe-hook
event; everything exports through whatever OTLP backend the host application has
wired (Langfuse, Tempo, Honeycomb, …). Reigner does not configure a provider or
an exporter — that's the deploying application's job.

Deliberately narrow: tokens, cost, and per-turn latency are the telemetry most
people want, but none of that is reachable from the plugin hook surface today
(``AgentState`` carries no usage). So this ships tool-call spans only; the richer
story waits on usage landing in state.

Dependency: ``opentelemetry-api`` only, imported lazily. A missing dependency
raises a clear :class:`ImportError` at construction rather than degrading to a
silent no-op — a configured-but-silent telemetry plugin is the worse surprise.
Install with ``pip install reigner[otel]``.

Zero-arg, so it works as a bare class path::

    plugins:
      - reigner.plugins.metrics.MetricsPlugin
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from reigner.plugins.base import Plugin

if TYPE_CHECKING:
    from reigner.harness.adapters.base import ToolCall
    from reigner.harness.events import (
        ErrorEvent,
        OracleEscalationEvent,
        SteeringAcceptedEvent,
        ToolResultEvent,
    )
    from reigner.harness.state import AgentState


class MetricsPlugin(Plugin):
    """Trace tool calls and loop events as OpenTelemetry spans."""

    name = "metrics"

    def __init__(self, *, tracer_name: str = "reigner") -> None:
        try:
            import opentelemetry.trace as trace
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise ImportError(
                "MetricsPlugin requires OpenTelemetry. Install it with `pip install reigner[otel]`."
            ) from exc
        self._tracer = trace.get_tracer(tracer_name)
        # One plugin instance serves concurrent sessions, so a tool's call id
        # alone can collide; key open spans on (session_id, call_id).
        self._open: dict[tuple[str, str], Any] = {}

    def _emit(self, name: str, attributes: dict[str, Any]) -> None:
        """Record a point-in-time observe event as a short standalone span."""
        span = self._tracer.start_span(name)
        for key, value in attributes.items():
            span.set_attribute(key, value)
        span.end()

    # --- tool-call span: opened in before, closed in after ----------------

    async def before_tool_call(self, call: ToolCall, state: AgentState) -> ToolCall:
        """Open a span for the tool call, closed by :meth:`after_tool_call`."""
        span = self._tracer.start_span(f"reigner.tool.{call.name}")
        span.set_attribute("reigner.session_id", state.session_id)
        span.set_attribute("reigner.tool", call.name)
        self._open[(state.session_id, call.id)] = span
        return call

    async def after_tool_call(
        self, call: ToolCall, result: ToolResultEvent, state: AgentState
    ) -> ToolResultEvent:
        """Close the tool-call span, annotating it with truncation/cache flags."""
        span = self._open.pop((state.session_id, call.id), None)
        if span is not None:
            span.set_attribute("reigner.truncated", result.truncated)
            span.set_attribute("reigner.cached", result.cached)
            span.end()
        return result

    # --- observe hooks: one short span each -------------------------------

    async def on_compaction(self, state: AgentState, level: int) -> None:
        """Emit a span for a compaction pass."""
        self._emit("reigner.compaction", {"reigner.level": level})

    async def on_error(self, error: ErrorEvent, state: AgentState) -> None:
        """Emit a span for an error event."""
        self._emit(
            "reigner.error",
            {"reigner.error": error.error, "reigner.recoverable": error.recoverable},
        )

    async def on_oracle_escalation(self, event: OracleEscalationEvent, state: AgentState) -> None:
        """Emit a span for an oracle escalation."""
        self._emit(
            "reigner.oracle",
            {"reigner.from_model": event.from_model, "reigner.to_model": event.to_model},
        )

    async def on_steering(self, event: SteeringAcceptedEvent, state: AgentState) -> None:
        """Emit a span for a steering message."""
        self._emit("reigner.steering", {"reigner.mode": event.mode})
