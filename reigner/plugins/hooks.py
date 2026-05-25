"""Hook names, the transform/observe classification, and the error raised when
a transform hook fails (SPEC §12).

:class:`reigner.plugins.host.PluginHost` reads these sets to pick its failure
policy: a transform-hook exception aborts the run (wrapped in
:class:`PluginHookError`), an observe-hook exception is logged and skipped.
"""

from __future__ import annotations

from typing import Final, Literal

HookName = Literal[
    "before_tool_call",
    "after_tool_call",
    "on_compaction",
    "on_final_answer",
    "on_error",
    "on_oracle_escalation",
    "on_steering",
]

TRANSFORM_HOOKS: Final[frozenset[str]] = frozenset(
    {"before_tool_call", "after_tool_call", "on_final_answer"}
)
"""Hooks that return a value folded plugin→plugin. A failure here must not let a
half-transformed value (e.g. un-redacted output) through, so it aborts the run."""

OBSERVE_HOOKS: Final[frozenset[str]] = frozenset(
    {"on_compaction", "on_error", "on_oracle_escalation", "on_steering"}
)
"""Pure side-effect hooks. A failure is logged and the run continues."""


class PluginHookError(Exception):
    """A transform hook raised.

    Carries the offending plugin name and hook; the original exception is
    preserved on ``__cause__``. The loop catches this and turns it into a
    terminal ``ErrorEvent``.
    """

    def __init__(self, plugin_name: str, hook: str, cause: Exception) -> None:
        super().__init__(f"plugin {plugin_name!r} failed in {hook}: {cause}")
        self.plugin_name = plugin_name
        self.hook = hook
