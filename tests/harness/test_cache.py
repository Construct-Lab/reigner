"""Unit tests for ToolResultCache (T-06, G9)."""

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
    stats = cache.stats()
    assert stats.size == 0
    assert stats.hits == 0
    assert stats.misses == 0  # clear() resets counters


def test_stats_counts_hits_and_misses() -> None:
    cache = ToolResultCache()
    assert cache.has("read", {"path": "a"}) is False  # miss
    cache.put("read", {"path": "a"}, "X")
    assert cache.has("read", {"path": "a"}) is True  # hit
    assert cache.has("read", {"path": "b"}) is False  # miss
    s = cache.stats()
    assert s.hits == 1
    assert s.misses == 2
    assert s.size == 1


def test_key_is_argument_order_independent() -> None:
    k1 = ToolResultCache.key("t", {"a": 1, "b": 2})
    k2 = ToolResultCache.key("t", {"b": 2, "a": 1})
    assert k1 == k2


def test_nested_dict_args_stable() -> None:
    cache = ToolResultCache()
    cache.put("t", {"q": {"a": 1, "b": 2}}, "X")
    assert cache.has("t", {"q": {"b": 2, "a": 1}})
