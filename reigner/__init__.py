"""Reigner: a single-agent, retrieval-shaped, citation-faithful agent library."""

from importlib.metadata import PackageNotFoundError, version

from reigner.plugins import Plugin
from reigner.sessions.store import SessionMeta, SessionStore
from reigner.tools.base import tool

try:
    __version__ = version("reigner")
except PackageNotFoundError:  # not installed (e.g. running from a bare source tree)
    __version__ = "0.0.0"

__all__ = ["Plugin", "SessionMeta", "SessionStore", "__version__", "tool"]
