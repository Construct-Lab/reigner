"""Strip configured regex patterns out of anything bound for the model (SPEC §12).

A transform plugin. It rewrites two surfaces:

- **Tool results** (``after_tool_call``) — the literal "before context" target.
  The result payload is an arbitrary JSON-coercible value, so the scrub walks
  it recursively and rewrites only string leaves; structure, keys, and scalars
  are left intact.
- **The final answer** (``on_final_answer``) — PII the model has already emitted
  is the worse leak, so the same patterns run over the answer text.

Both are transform hooks, so a failure here raises through
:class:`~reigner.plugins.host.PluginHost` and aborts the run rather than letting
a half-redacted value reach the model or the user.

Configuration: the plugin takes patterns, so it can't be a bare class path in
``reigner.yaml`` — construct it and reference the instance::

    # myproject/observability.py
    from reigner.plugins import PiiRedactPlugin
    redactor = PiiRedactPlugin(patterns=[r"\\b\\d{3}-\\d{2}-\\d{4}\\b", EMAIL_RE])

    # reigner.yaml
    plugins:
      - myproject.observability:redactor

Caveat worth stating loudly: regex catches *structured* PII (SSNs, emails, card
numbers) but not names or addresses. Treat it as a backstop, not a guarantee.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from reigner.plugins.base import Plugin

if TYPE_CHECKING:
    from reigner.harness.adapters.base import ToolCall
    from reigner.harness.events import FinalAnswerEvent, ToolResultEvent
    from reigner.harness.state import AgentState

DEFAULT_TOKEN = "[REDACTED]"


class PiiRedactPlugin(Plugin):
    """Replace regex matches with a token in tool results and the final answer."""

    name = "pii_redact"

    def __init__(
        self,
        patterns: list[str | re.Pattern[str]],
        *,
        token: str = DEFAULT_TOKEN,
    ) -> None:
        """Compile ``patterns`` up front so a bad pattern fails loudly at wiring time.

        Each entry is a regex string or an already-compiled pattern. ``token`` is
        the replacement substituted for every match.
        """
        self._patterns: list[re.Pattern[str]] = [
            re.compile(p) if isinstance(p, str) else p for p in patterns
        ]
        self._token = token

    def _scrub(self, value: Any) -> Any:
        """Recurse a JSON-coercible value, rewriting only string leaves.

        Dicts and lists are rebuilt with scrubbed children; strings have every
        pattern applied; ints, floats, bools, and ``None`` pass through untouched
        so a numeric metric never turns into ``[REDACTED]``.
        """
        if isinstance(value, str):
            for pattern in self._patterns:
                value = pattern.sub(self._token, value)
            return value
        if isinstance(value, dict):
            return {k: self._scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._scrub(v) for v in value]
        return value

    async def after_tool_call(
        self, call: ToolCall, result: ToolResultEvent, state: AgentState
    ) -> ToolResultEvent:
        """Scrub the result payload before it lands in the model's context."""
        return replace(result, result=self._scrub(result.result))

    async def on_final_answer(
        self, answer: FinalAnswerEvent, state: AgentState
    ) -> FinalAnswerEvent:
        """Scrub the answer text before it is emitted to the user."""
        return replace(answer, text=self._scrub(answer.text))
