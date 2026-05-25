"""Hook-based extension points for the agent loop (SPEC §12).

Subclass :class:`Plugin`, override the hooks you need, and list the dotted path
in ``reigner.yaml`` under ``plugins:``. :class:`PluginHost` is the dispatcher
the loop drives; most users never touch it directly.
"""

from reigner.plugins.base import Plugin
from reigner.plugins.host import PluginHost
from reigner.plugins.registry import load_plugins

__all__ = ["Plugin", "PluginHost", "load_plugins"]
