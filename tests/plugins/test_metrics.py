"""MetricsPlugin: lazy-dep failure, span correlation, observe-hook isolation (SPEC §12).

Two worlds: without the ``otel`` extra the missing-dependency path runs and the
span tests skip; with ``opentelemetry-api`` present the span tests run against a
fake tracer (no SDK/exporter needed) and the missing-dependency test skips.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

import pytest

from reigner.harness.events import ToolResultEvent

OTEL_PRESENT = importlib.util.find_spec("opentelemetry") is not None


# --------------------------------------------------------------------------
# Fakes — let the span tests run with only opentelemetry-api (no SDK exporter)
# --------------------------------------------------------------------------


class FakeSpan:
    def __init__(self, name: str) -> None:
        self.name = name
        self.attributes: dict[str, Any] = {}
        self.ended = False

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def end(self) -> None:
        self.ended = True


class FakeTracer:
    def __init__(self) -> None:
        self.spans: list[FakeSpan] = []

    def start_span(self, name: str) -> FakeSpan:
        span = FakeSpan(name)
        self.spans.append(span)
        return span


@dataclass(frozen=True)
class FakeCall:
    id: str
    name: str


class FakeState:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id


def _result(call_id: str, *, truncated: bool = False, cached: bool = False) -> ToolResultEvent:
    return ToolResultEvent(
        seq=1,
        session_id="s",
        turn=0,
        call_id=call_id,
        result={},
        truncated=truncated,
        cached=cached,
    )


def _plugin_with_fake_tracer() -> tuple[Any, FakeTracer]:
    from reigner.plugins.metrics import MetricsPlugin

    plugin = MetricsPlugin()
    tracer = FakeTracer()
    plugin._tracer = tracer
    return plugin, tracer


# --------------------------------------------------------------------------
# Missing dependency
# --------------------------------------------------------------------------


@pytest.mark.skipif(OTEL_PRESENT, reason="opentelemetry installed; missing-dep path not exercised")
def test_missing_dependency_raises_with_install_hint() -> None:
    from reigner.plugins.metrics import MetricsPlugin

    with pytest.raises(ImportError, match=r"reigner\[otel\]"):
        MetricsPlugin()


def test_module_imports_without_opentelemetry() -> None:
    # Importing the module (and the class) must never import opentelemetry —
    # only instantiation does. Guards the package __init__ export.
    from reigner.plugins.metrics import MetricsPlugin

    assert MetricsPlugin.name == "metrics"


# --------------------------------------------------------------------------
# Span correlation (needs opentelemetry-api)
# --------------------------------------------------------------------------

pytestmark_otel = pytest.mark.skipif(not OTEL_PRESENT, reason="needs opentelemetry-api")


@pytestmark_otel
async def test_tool_call_opens_then_closes_one_span() -> None:
    plugin, tracer = _plugin_with_fake_tracer()
    call, state = FakeCall(id="c1", name="grep_artifact"), FakeState("sess-a")

    await plugin.before_tool_call(call, state)
    assert len(tracer.spans) == 1
    span = tracer.spans[0]
    assert span.name == "reigner.tool.grep_artifact"
    assert not span.ended

    await plugin.after_tool_call(call, _result("c1", truncated=True), state)
    assert span.ended
    assert span.attributes["reigner.truncated"] is True
    assert span.attributes["reigner.session_id"] == "sess-a"


@pytestmark_otel
async def test_same_call_id_across_sessions_does_not_collide() -> None:
    plugin, tracer = _plugin_with_fake_tracer()
    a, b = FakeState("sess-a"), FakeState("sess-b")
    call = FakeCall(id="dup", name="read")

    await plugin.before_tool_call(call, a)
    await plugin.before_tool_call(call, b)
    await plugin.after_tool_call(call, _result("dup"), a)

    # Closing session a leaves session b's span open — keys are disjoint.
    span_a, span_b = tracer.spans
    assert span_a.ended and not span_b.ended


@pytestmark_otel
async def test_observe_hooks_emit_short_spans() -> None:
    plugin, tracer = _plugin_with_fake_tracer()
    await plugin.on_compaction(FakeState("s"), level=2)
    (span,) = tracer.spans
    assert span.name == "reigner.compaction"
    assert span.attributes["reigner.level"] == 2
    assert span.ended  # point-in-time span is opened and closed in one call
