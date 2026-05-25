"""The plugin dispatcher (SPEC §12).

``PluginHost`` owns the ordered plugin list and applies the hooks with a split
failure policy:

- **Transform** hooks fold plugin→plugin — one plugin's return value is the
  next plugin's input. A raised exception is wrapped in :class:`PluginHookError`
  and propagates, so the loop turns it into a terminal ``ErrorEvent`` and stops.
  Nothing half-transformed (e.g. an un-redacted result) reaches the model.
- **Observe** hooks run every plugin in order; an exception is logged and the
  next plugin still runs. A flaky audit or metrics sink can't take down a run.

The loop holds exactly one host. ``PluginHost.empty()`` is the no-op used when
no plugins are configured, so the loop never branches on "are there plugins".
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from reigner.plugins.hooks import PluginHookError

if TYPE_CHECKING:
    from reigner.harness.adapters.base import ToolCall
    from reigner.harness.events import (
        ErrorEvent,
        FinalAnswerEvent,
        OracleEscalationEvent,
        SteeringAcceptedEvent,
        ToolResultEvent,
    )
    from reigner.harness.state import AgentState
    from reigner.plugins.base import Plugin

log = logging.getLogger("reigner.plugins")


class PluginHost:
    """Dispatches the seven hooks across an ordered list of plugins."""

    def __init__(self, plugins: list[Plugin]) -> None:
        self._plugins = list(plugins)

    @classmethod
    def empty(cls) -> PluginHost:
        """A host with no plugins — every hook is a pass-through no-op."""
        return cls([])

    def __bool__(self) -> bool:
        return bool(self._plugins)

    def __len__(self) -> int:
        return len(self._plugins)

    @staticmethod
    def _label(plugin: Plugin) -> str:
        return plugin.name or type(plugin).__name__

    # ------------------------------------------------------------------
    # Transform hooks — fold plugin→plugin, fail loud.
    # ------------------------------------------------------------------

    async def before_tool_call(self, call: ToolCall, state: AgentState) -> ToolCall:
        for p in self._plugins:
            try:
                call = await p.before_tool_call(call, state)
            except Exception as exc:
                raise PluginHookError(self._label(p), "before_tool_call", exc) from exc
        return call

    async def after_tool_call(
        self, call: ToolCall, result: ToolResultEvent, state: AgentState
    ) -> ToolResultEvent:
        for p in self._plugins:
            try:
                result = await p.after_tool_call(call, result, state)
            except Exception as exc:
                raise PluginHookError(self._label(p), "after_tool_call", exc) from exc
        return result

    async def on_final_answer(
        self, answer: FinalAnswerEvent, state: AgentState
    ) -> FinalAnswerEvent:
        for p in self._plugins:
            try:
                answer = await p.on_final_answer(answer, state)
            except Exception as exc:
                raise PluginHookError(self._label(p), "on_final_answer", exc) from exc
        return answer

    # ------------------------------------------------------------------
    # Observe hooks — run all, isolate failures.
    # ------------------------------------------------------------------

    async def on_compaction(self, state: AgentState, level: int) -> None:
        for p in self._plugins:
            try:
                await p.on_compaction(state, level)
            except Exception:
                log.warning("plugin %s on_compaction failed", self._label(p), exc_info=True)

    async def on_error(self, error: ErrorEvent, state: AgentState) -> None:
        for p in self._plugins:
            try:
                await p.on_error(error, state)
            except Exception:
                log.warning("plugin %s on_error failed", self._label(p), exc_info=True)

    async def on_oracle_escalation(self, event: OracleEscalationEvent, state: AgentState) -> None:
        for p in self._plugins:
            try:
                await p.on_oracle_escalation(event, state)
            except Exception:
                log.warning("plugin %s on_oracle_escalation failed", self._label(p), exc_info=True)

    async def on_steering(self, event: SteeringAcceptedEvent, state: AgentState) -> None:
        for p in self._plugins:
            try:
                await p.on_steering(event, state)
            except Exception:
                log.warning("plugin %s on_steering failed", self._label(p), exc_info=True)
