"""The ``Plugin`` base class and its seven hook methods (SPEC §12).

Plugins are extension points for behaviour the core package can't anticipate —
audit logging, telemetry, redaction, rate limiting. Subclass :class:`Plugin`
and override only the hooks you care about; every method here is a safe no-op
default, so a plugin that only logs tool calls implements one method.

Two kinds of hook, distinguished by what they return (see
:mod:`reigner.plugins.hooks`):

- **Transform** hooks (``before_tool_call``, ``after_tool_call``,
  ``on_final_answer``) return a — possibly modified — value that flows on
  through the loop. Returning the input unchanged is the no-op. The host folds
  these plugin-to-plugin and treats a raised exception as fatal.
- **Observe** hooks (``on_compaction``, ``on_error``, ``on_oracle_escalation``,
  ``on_steering``) are pure side effects and return ``None``. The host isolates
  them: a raised exception is logged and the next plugin still runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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


class Plugin:
    """Base for all plugins. Override the hooks you need; the rest no-op.

    ``name`` is used in logs and error messages; it defaults to the class name
    when left blank.
    """

    name: str = ""

    async def before_tool_call(self, call: ToolCall, state: AgentState) -> ToolCall:
        """Inspect or rewrite a tool call before it runs. Return the call."""
        return call

    async def after_tool_call(
        self, call: ToolCall, result: ToolResultEvent, state: AgentState
    ) -> ToolResultEvent:
        """Inspect or rewrite a tool result after truncation. Return the result.

        ``result`` is the bounded :class:`ToolResultEvent` (so ``result.truncated``
        is meaningful); a returned copy with a rewritten ``result`` payload is
        what lands in both the model's context and the emitted event.
        """
        return result

    async def on_compaction(self, state: AgentState, level: int) -> None:
        """Observe a compaction tier firing (``level`` is the tier index)."""

    async def on_final_answer(
        self, answer: FinalAnswerEvent, state: AgentState
    ) -> FinalAnswerEvent:
        """Inspect or rewrite the final answer before it is emitted."""
        return answer

    async def on_error(self, error: ErrorEvent, state: AgentState) -> None:
        """Observe a terminal error before it is emitted."""

    async def on_oracle_escalation(self, event: OracleEscalationEvent, state: AgentState) -> None:
        """Observe a single-turn oracle escalation being armed."""

    async def on_steering(self, event: SteeringAcceptedEvent, state: AgentState) -> None:
        """Observe a queued steering message being accepted into the loop."""
