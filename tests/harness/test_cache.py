"""Unit tests for ToolResultCache (T-05 / issue #5)."""

from __future__ import annotations

from reigner.harness.cache import ToolResultCache


def test_miss_then_hit() -> None:
    cache = ToolResultCache()
    assert not cache.has("read", {"path": "a.txt"})
    cache.put("read", {"path": "a.txt"}, {"content": "hello"})
    assert cache.has("read", {"path": "a.txt"})
    assert cache.get("read", {"path": "a.txt"}) == {"content": "hello"}


def test_args_order_independent() -> None:
    cache = ToolResultCache()
    cache.put("read", {"path": "a", "offset": 0}, "X")
    assert cache.has("read", {"offset": 0, "path": "a"})


def test_distinct_args_distinct_entries() -> None:
    cache = ToolResultCache()
    cache.put("read", {"path": "a"}, 1)
    cache.put("read", {"path": "b"}, 2)
    assert cache.get("read", {"path": "a"}) == 1
    assert cache.get("read", {"path": "b"}) == 2
    assert len(cache) == 2


def test_distinct_tool_names_distinct_entries() -> None:
    cache = ToolResultCache()
    cache.put("read", {"path": "a"}, 1)
    cache.put("grep", {"path": "a"}, 2)
    assert cache.get("read", {"path": "a"}) == 1
    assert cache.get("grep", {"path": "a"}) == 2


def test_clear() -> None:
    cache = ToolResultCache()
    cache.put("read", {"path": "a"}, 1)
    cache.clear()
    assert len(cache) == 0
    assert not cache.has("read", {"path": "a"})
