"""Cross-module type aliases and small shared helpers.

Kept deliberately narrow: only orphans that don't have a natural home elsewhere
in the package live here. Domain types (events, prompts, tool specs) stay with
their owning module.

See T-17 / issue #17.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Literal

ProviderName = Literal["openai", "anthropic", "gemini"]
"""LLM provider id accepted in ``reigner.yaml`` and used to pick an adapter."""

DottedPath = str
"""Doc-only alias for a Python import path.

Accepted forms:
- ``pkg.mod:obj`` — explicit attribute (preferred)
- ``pkg.mod.Class`` — attribute is the last dotted segment
"""

Profile = Literal["full", "read_only", "eval"]
"""Named tool-permission subset (SPEC §6.3). Re-exported by ``harness.agent``
for back-compat; canonical home is here."""


class ConfigError(Exception):
    """Raised when configuration cannot be loaded, validated, or resolved.

    Wraps the underlying cause (e.g. ``pydantic.ValidationError``,
    ``ImportError``) on ``__cause__`` so callers can drill in if they need to.
    """


def import_dotted(path: DottedPath) -> Any:
    """Resolve a dotted import path to its object.

    Accepts both ``pkg.mod:obj`` (explicit separator) and ``pkg.mod.Class``
    (last segment is the attribute name). Raises ``ConfigError`` with the
    offending path on any failure, preserving the original exception on
    ``__cause__``.
    """
    if not path or not isinstance(path, str):
        raise ConfigError(f"dotted path must be a non-empty string, got {path!r}")

    if ":" in path:
        module_name, _, attr = path.partition(":")
    else:
        module_name, _, attr = path.rpartition(".")

    if not module_name or not attr:
        raise ConfigError(
            f"dotted path {path!r} must be of the form 'pkg.mod:obj' or 'pkg.mod.attr'"
        )

    try:
        module = import_module(module_name)
    except ImportError as e:
        raise ConfigError(f"cannot import module {module_name!r} from path {path!r}: {e}") from e

    try:
        return getattr(module, attr)
    except AttributeError as e:
        raise ConfigError(f"module {module_name!r} has no attribute {attr!r}") from e


__all__ = [
    "ConfigError",
    "DottedPath",
    "Profile",
    "ProviderName",
    "import_dotted",
]
