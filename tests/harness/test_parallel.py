"""Unit tests for harness.parallel (T-06, G11)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from reigner.harness.adapters.base import ToolCall
from reigner.harness.cache import ToolResultCache
from reigner.harness.parallel import execute_batch, execute_one, should_parallelize


@dataclass
class _StubTool:
    name: str
    readonly: bool = True
    fn: Any = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def run(self, args: dict[str, Any]) -> Any:
        self.calls.append(args)
        if self.fn is None:
            return {"echo": args}
        return await self.fn(args)


def _tc(name: str, args: dict[str, Any] | None = None, call_id: str = "c1") -> ToolCall:
    return ToolCall(id=call_id, name=name, args=args or {})


@pytest.mark.asyncio
async def test_cache_hit_short_circuits_execution() -> None:
    tool = _StubTool(name="read", readonly=True)
    cache = ToolResultCache()
    cache.put("read", {"path": "a"}, "cached")

    result = await execute_one(_tc("read", {"path": "a"}), tool=tool, cache=cache)

    assert result.cache_hit is True
    assert result.raw == "cached"
    assert tool.calls == []  # never invoked


@pytest.mark.asyncio
async def test_successful_readonly_result_is_cached() -> None:
    tool = _StubTool(name="read", readonly=True)
    cache = ToolResultCache()

    await execute_one(_tc("read", {"path": "a"}), tool=tool, cache=cache)

    assert cache.has("read", {"path": "a"})


@pytest.mark.asyncio
async def test_errors_are_not_cached() -> None:
    async def boom(_: dict[str, Any]) -> Any:
        raise RuntimeError("nope")

    tool = _StubTool(name="read", readonly=True, fn=boom)
    cache = ToolResultCache()

    result = await execute_one(_tc("read", {"path": "a"}), tool=tool, cache=cache)

    assert result.errored is True
    assert not cache.has("read", {"path": "a"})


@pytest.mark.asyncio
async def test_writes_are_not_cached() -> None:
    tool = _StubTool(name="write", readonly=False)
    cache = ToolResultCache()

    await execute_one(_tc("write", {"path": "a"}), tool=tool, cache=cache)

    assert not cache.has("write", {"path": "a"})


@pytest.mark.asyncio
async def test_unknown_tool_returns_error() -> None:
    cache = ToolResultCache()
    result = await execute_one(_tc("missing"), tool=None, cache=cache)
    assert result.errored is True
    assert "unknown tool" in result.raw["error"]


def test_should_parallelize_all_readonly() -> None:
    tools = {"r1": _StubTool("r1"), "r2": _StubTool("r2")}
    assert should_parallelize([_tc("r1"), _tc("r2")], tools) is True


def test_should_parallelize_mixed_fails_safe() -> None:
    tools = {"r": _StubTool("r"), "w": _StubTool("w", readonly=False)}
    assert should_parallelize([_tc("r"), _tc("w")], tools) is False


def test_should_parallelize_unknown_tool_fails_safe() -> None:
    tools = {"r": _StubTool("r")}
    assert should_parallelize([_tc("r"), _tc("missing")], tools) is False


def test_should_parallelize_empty_is_false() -> None:
    assert should_parallelize([], {}) is False


@pytest.mark.asyncio
async def test_execute_batch_runs_in_parallel_when_allowed() -> None:
    started = asyncio.Event()
    finishing = asyncio.Event()

    async def slow_first(_: dict[str, Any]) -> Any:
        started.set()
        await finishing.wait()
        return "first"

    async def fast_second(_: dict[str, Any]) -> Any:
        # Only succeeds if it runs concurrently with the first call.
        await asyncio.wait_for(started.wait(), timeout=1.0)
        finishing.set()
        return "second"

    tools = {
        "a": _StubTool("a", fn=slow_first),
        "b": _StubTool("b", fn=fast_second),
    }
    cache = ToolResultCache()

    results = await execute_batch(
        [_tc("a", call_id="1"), _tc("b", call_id="2")],
        tools_by_name=tools,
        cache=cache,
        parallel=True,
    )
    assert [r.raw for r in results] == ["first", "second"]


@pytest.mark.asyncio
async def test_execute_batch_preserves_order_in_serial() -> None:
    tools = {"a": _StubTool("a"), "b": _StubTool("b")}
    cache = ToolResultCache()
    results = await execute_batch(
        [_tc("a", {"i": 1}, call_id="1"), _tc("b", {"i": 2}, call_id="2")],
        tools_by_name=tools,
        cache=cache,
        parallel=False,
    )
    assert results[0].raw == {"echo": {"i": 1}}
    assert results[1].raw == {"echo": {"i": 2}}
