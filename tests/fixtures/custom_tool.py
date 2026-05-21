"""A @tool-decorated callable referenced by `tests.fixtures.custom_tool:my_custom_tool`.

Used by ``test_from_config_custom_tools_imported`` to exercise the dotted-path
loading branch of ``Harness.from_config`` end-to-end through the registry.
"""

from __future__ import annotations

from reigner.tools.base import tool


@tool(readonly=True)
async def my_custom_tool(query: str) -> dict[str, str]:
    """A tiny custom tool that just echoes its input."""
    return {"echo": query}
