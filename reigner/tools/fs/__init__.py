"""Raw filesystem tools — opt-in surface for recipes that need them.

``FsTools`` is the public handle; the concrete tool functions live in
sibling modules and are reached via :meth:`FsTools.tools` rather than
imported directly, so consumers can't construct an unbound tool.

Raw FS tools are documented as risky relative to the artifact tools
(SPEC §6.5): they are bounded by configurable caps but they are not
self-describing in the same way artifact tools are — there is no schema
behind the paths, only the project's repo on disk.
"""

from reigner.tools.fs.store import FsTools

__all__ = ["FsTools"]
