"""Hook-based extension points for the agent loop (SPEC §12).

Subclass :class:`Plugin`, override the hooks you need, and list the dotted path
in ``reigner.yaml`` under ``plugins:``. :class:`PluginHost` is the dispatcher
the loop drives; most users never touch it directly.

Two plugins ship in the box: :class:`MetricsPlugin` (OpenTelemetry spans, needs
the ``otel`` extra) and :class:`PiiRedactPlugin` (regex redaction of tool results
and the final answer). Importing them here is cheap — neither pulls a heavy
dependency at import time; ``MetricsPlugin`` only touches OpenTelemetry when
instantiated.
"""

from reigner.plugins.base import Plugin
from reigner.plugins.host import PluginHost
from reigner.plugins.metrics import MetricsPlugin
from reigner.plugins.pii_redact import PiiRedactPlugin
from reigner.plugins.registry import load_plugins

__all__ = [
    "MetricsPlugin",
    "PiiRedactPlugin",
    "Plugin",
    "PluginHost",
    "load_plugins",
]
