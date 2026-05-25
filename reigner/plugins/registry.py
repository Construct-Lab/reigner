"""Load the plugins listed in ``reigner.yaml`` by dotted path (SPEC §12).

Each entry resolves via :func:`reigner.types.import_dotted` to either a
:class:`Plugin` subclass — instantiated with no arguments — or an already-built
:class:`Plugin` instance, which is used as-is. Anything else is a configuration
error. Plugins that need parameters (patterns, rate limits) are constructed by
the user and referenced as a pre-built instance, so the yaml stays a flat list
of paths with no per-plugin config block.
"""

from __future__ import annotations

from reigner.plugins.base import Plugin
from reigner.types import ConfigError, DottedPath, import_dotted


def load_plugins(paths: list[DottedPath]) -> list[Plugin]:
    """Resolve dotted paths to live :class:`Plugin` instances, in order."""
    plugins: list[Plugin] = []
    for path in paths:
        obj = import_dotted(path)
        if isinstance(obj, type):
            if not issubclass(obj, Plugin):
                raise ConfigError(
                    f"plugin path {path!r} resolved to class {obj.__name__!r}, "
                    "which is not a Plugin subclass"
                )
            plugins.append(obj())
        elif isinstance(obj, Plugin):
            plugins.append(obj)
        else:
            raise ConfigError(
                f"plugin path {path!r} resolved to {type(obj).__name__!r}, "
                "expected a Plugin subclass or instance"
            )
    return plugins
