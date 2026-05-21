"""BM25 search tools flow through G11 parallel execution and the G9 cache.

The adapter must keep `readonly=True` flat so `should_parallelize` sees it,
and adapter results must round-trip through `ToolResultCache` on repeat calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reigner.harness.adapters.base import ToolCall
from reigner.harness.cache import ToolResultCache
from reigner.harness.parallel import execute_batch, should_parallelize
from reigner.tools.search import Bm25Index


def _write_index(tmp_path: Path) -> Path:
    p = tmp_path / "idx.json"
    p.write_text(
        json.dumps(
            [
                {
                    "id": f"doc-{i}",
                    "identifiers": {},
                    "text": "apple banana cherry",
                    "sections": {},
                    "source": "",
                }
                for i in range(3)
            ]
        )
    )
    return p


def _tools_by_name(tmp_path: Path) -> dict:
    index = Bm25Index(path=_write_index(tmp_path))
    return {t.name: t for t in index.tools()}


def test_search_tools_should_parallelize_when_all_readonly(tmp_path: Path) -> None:
    tools = _tools_by_name(tmp_path)
    calls = [
        ToolCall(id="1", name="bm25_search", args={"query": "apple"}),
        ToolCall(id="2", name="bm25_search", args={"query": "banana"}),
        ToolCall(id="3", name="bm25_search", args={"query": "cherry"}),
    ]
    assert should_parallelize(calls, tools) is True


@pytest.mark.asyncio
async def test_three_concurrent_searches_execute_in_parallel(tmp_path: Path) -> None:
    tools = _tools_by_name(tmp_path)
    cache = ToolResultCache()
    calls = [
        ToolCall(id="1", name="bm25_search", args={"query": "apple"}),
        ToolCall(id="2", name="bm25_search", args={"query": "banana"}),
        ToolCall(id="3", name="bm25_search", args={"query": "cherry"}),
    ]
    results = await execute_batch(calls, tools_by_name=tools, cache=cache, parallel=True)
    assert len(results) == 3
    assert all(not r.errored for r in results)
    assert all(not r.cache_hit for r in results)


@pytest.mark.asyncio
async def test_repeated_search_hits_g9_cache(tmp_path: Path) -> None:
    tools = _tools_by_name(tmp_path)
    cache = ToolResultCache()
    call = ToolCall(id="1", name="bm25_search", args={"query": "apple"})

    first = await execute_batch([call], tools_by_name=tools, cache=cache, parallel=False)
    assert first[0].cache_hit is False

    second = await execute_batch(
        [ToolCall(id="2", name="bm25_search", args={"query": "apple"})],
        tools_by_name=tools,
        cache=cache,
        parallel=False,
    )
    assert second[0].cache_hit is True
    assert second[0].raw == first[0].raw
