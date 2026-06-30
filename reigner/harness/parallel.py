"""Parallel read execution (G11).

When every real (non-pseudo) tool call in one model turn is ``readonly=True``,
the loop dispatches them concurrently via ``asyncio.gather``. Mixed batches
fall back to serial execution because a write could observe state a read in
the same batch produced. The cache (G9) is consulted before any execution; a
cache hit short-circuits the tool call entirely.

This module owns the *execution* — the loop owns event emission and history
mutation so the loop file stays the one place all special cases live.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from reigner.harness.adapters.base import ToolCall
from reigner.harness.cache import ToolResultCache


@runtime_checkable
class RunnableTool(Protocol):
    """Minimum runtime surface needed to execute a tool.

    Declared with ``@property`` so adapters whose attributes are read-only
    descriptors (e.g. ``RunnableToolAdapter``) structurally satisfy the
    Protocol under mypy.
    """

    @property
    def name(self) -> str:
        """The tool's registered name."""
        ...

    @property
    def readonly(self) -> bool:
        """Whether the tool is side-effect-free."""
        ...

    async def run(self, args: dict[str, Any]) -> Any:
        """Invoke the tool with a dict of keyword arguments."""
        ...


@dataclass(frozen=True)
class ExecutionResult:
    """One tool call's outcome. Ordered alongside the input call list."""

    raw: Any
    cache_hit: bool
    errored: bool


async def execute_one(
    tc: ToolCall,
    *,
    tool: RunnableTool | None,
    cache: ToolResultCache,
) -> ExecutionResult:
    """Run one real tool call. Cache hits skip execution.

    Only successful results from ``readonly`` tools are cached — errors are
    never memoized (a transient failure may succeed on retry) and writes
    bypass the cache entirely.
    """
    if tool is None:
        return ExecutionResult(
            raw={"error": f"unknown tool: {tc.name}"}, cache_hit=False, errored=True
        )

    if tool.readonly and cache.has(tc.name, tc.args):
        return ExecutionResult(raw=cache.get(tc.name, tc.args), cache_hit=True, errored=False)

    try:
        raw = await tool.run(tc.args)
    except Exception as exc:  # noqa: BLE001 — tool errors are reported to the model, not raised
        return ExecutionResult(
            raw={"error": f"{type(exc).__name__}: {exc}"}, cache_hit=False, errored=True
        )

    if tool.readonly:
        cache.put(tc.name, tc.args, raw)
    return ExecutionResult(raw=raw, cache_hit=False, errored=False)


def should_parallelize(
    calls: list[ToolCall],
    tools_by_name: Mapping[str, RunnableTool],
) -> bool:
    """Return True iff every call resolves to a known ``readonly`` tool.

    Unknown tools are *not* parallelizable: we don't know whether they write,
    and the safe default is serial execution.
    """
    if not calls:
        return False
    for tc in calls:
        tool = tools_by_name.get(tc.name)
        if tool is None or not tool.readonly:
            return False
    return True


async def execute_batch(
    calls: list[ToolCall],
    *,
    tools_by_name: Mapping[str, RunnableTool],
    cache: ToolResultCache,
    parallel: bool,
) -> list[ExecutionResult]:
    """Execute ``calls`` and return results in the same order.

    ``parallel=True`` gathers all calls concurrently; ``False`` runs them
    sequentially. The caller decides via :func:`should_parallelize`.
    """
    if parallel and len(calls) > 1:
        return list(
            await asyncio.gather(
                *(execute_one(tc, tool=tools_by_name.get(tc.name), cache=cache) for tc in calls)
            )
        )
    results: list[ExecutionResult] = []
    for tc in calls:
        results.append(await execute_one(tc, tool=tools_by_name.get(tc.name), cache=cache))
    return results


__all__ = [
    "ExecutionResult",
    "RunnableTool",
    "execute_batch",
    "execute_one",
    "should_parallelize",
]
