from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reigner.artifacts import ArtifactSchema, JsonArtifactSpec, SectionSpec
from reigner.ingestion import MapReduceExtractor
from tests.ingestion.conftest import StubAdapter


def _schema() -> ArtifactSchema:
    return ArtifactSchema(
        entity_path="{course}/{topic}",
        sections=[
            SectionSpec(name="overview/summary", required=True, max_chars=40),
            SectionSpec(name="topic/a", max_chars=30),
            SectionSpec(name="topic/b", max_chars=30),
            SectionSpec(name="extras/*"),  # glob — omitted from the section spec
        ],
        json_artifacts=[
            JsonArtifactSpec(name="coverage.json", fields={"a": bool, "b": bool}),
        ],
    )


class _Extractor(MapReduceExtractor):
    """Minimal map-reduce subclass driven by a StubAdapter in the tests below."""

    schema = _schema()
    MAP_PROMPT = "sections:\n{section_spec}\nfile={filename}"
    REDUCE_PROMPT = "merge {section} <= {max_chars} file={filename}"
    base_backoff_seconds = 0.0
    chunk_chars = 100  # small so the fixtures cross chunk boundaries
    MAP_EXCLUDE = frozenset({"overview/summary"})

    async def preprocess_pdf(self, raw: bytes) -> str:
        # Tests feed plain text (already \f-paginated), not real PDF bytes.
        return raw.decode()

    def prompt_context(self, meta: dict[str, Any]) -> dict[str, Any]:
        return {"filename": meta.get("filename", "unknown")}

    async def summarize(self, sections: dict[str, str], meta: dict[str, Any]) -> dict[str, str]:
        meta["title"] = "Derived Title"
        return {"overview/summary": "summary of: " + ", ".join(sorted(sections))}

    def post_process(
        self, sections: dict[str, str], meta: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        return {
            "coverage.json": {
                "a": bool(sections.get("topic/a", "").strip()),
                "b": bool(sections.get("topic/b", "").strip()),
                "title": meta.get("title", ""),
            }
        }


def _map(**sections: str) -> str:
    return json.dumps(sections)


def _content(text: str) -> str:
    return json.dumps({"content": text})


def _adapter(*responses: str) -> StubAdapter:
    return StubAdapter(responses=list(responses))


def _page(text: str, size: int) -> str:
    """A single page of roughly `size` chars."""
    return (text * size)[:size]


# ---- Page packing ---------------------------------------------------------


def test_chunk_packs_pages_without_splitting() -> None:
    ext = _Extractor(adapter=_adapter())
    # Three ~40-char pages, chunk_chars=100 -> pages 1+2 in one window, page 3 alone.
    text = "\f".join([_page("a", 40), _page("b", 40), _page("c", 40)])
    chunks = ext._chunk_pages(text)
    assert len(chunks) == 2
    assert chunks[0].count("a") == 40 and chunks[0].count("b") == 40
    assert chunks[1].count("c") == 40
    # No page was split: every original page's content survives intact.
    assert "a" * 40 in chunks[0] and "b" * 40 in chunks[0]


def test_oversized_page_becomes_its_own_chunk() -> None:
    ext = _Extractor(adapter=_adapter())
    big = _page("x", 250)  # larger than chunk_chars=100
    text = "\f".join([_page("a", 40), big, _page("b", 40)])
    chunks = ext._chunk_pages(text)
    # The oversized page is isolated, whole, and over budget — never split/dropped.
    assert big in chunks
    over = [c for c in chunks if c == big]
    assert len(over) == 1 and len(over[0]) == 250


def test_blank_pages_skipped() -> None:
    ext = _Extractor(adapter=_adapter())
    chunks = ext._chunk_pages("real page\f\f   \fanother")
    assert chunks == ["real page\n\nanother"]


# ---- Section spec rendering ------------------------------------------------


def test_section_spec_omits_globs_and_excluded() -> None:
    ext = _Extractor(adapter=_adapter())
    spec = ext._section_spec()
    assert "topic/a (<=30 chars)" in spec
    assert "topic/b (<=30 chars)" in spec
    assert "overview/summary" not in spec  # MAP_EXCLUDE
    assert "extras" not in spec  # glob


# ---- Fragment collection across chunks -------------------------------------


async def test_fragments_collected_across_chunks() -> None:
    # Two chunks each contribute to topic/a; topic/b only in the second.
    adapter = _adapter(
        _map(**{"topic/a": "first a"}),
        _map(**{"topic/a": "second a", "topic/b": "only b"}),
    )
    ext = _Extractor(adapter=adapter)
    chunks = ["chunk one", "chunk two"]
    fragments = await ext._map(chunks, {"filename": "doc.pdf"})
    assert fragments == {"topic/a": ["first a", "second a"], "topic/b": ["only b"]}


async def test_invented_section_names_dropped() -> None:
    adapter = _adapter(_map(**{"topic/a": "kept", "not/a/section": "dropped"}))
    ext = _Extractor(adapter=adapter)
    fragments = await ext._map(["chunk"], {"filename": "doc.pdf"})
    assert fragments == {"topic/a": ["kept"]}


async def test_empty_fragments_ignored() -> None:
    adapter = _adapter(_map(**{"topic/a": "  ", "topic/b": "real"}))
    ext = _Extractor(adapter=adapter)
    fragments = await ext._map(["chunk"], {"filename": "doc.pdf"})
    assert fragments == {"topic/b": ["real"]}


async def test_map_prompt_carries_section_spec_and_context() -> None:
    adapter = _adapter(_map(**{"topic/a": "x"}))
    ext = _Extractor(adapter=adapter)
    await ext._map(["chunk"], {"filename": "doc.pdf"})
    sent = adapter.calls[0][0].stable
    assert "topic/a (<=30 chars)" in sent
    assert "file=doc.pdf" in sent


# ---- Reduce: single fragment vs merge --------------------------------------


async def test_single_fitting_fragment_skips_model_call() -> None:
    adapter = _adapter()  # no responses — a model call would raise
    ext = _Extractor(adapter=adapter)
    out = await ext.reduce({"topic/a": ["short fragment"]}, {"filename": "d"})
    assert out == {"topic/a": "short fragment"}
    assert adapter.remaining == 0  # nothing consumed; no call happened


async def test_multiple_fragments_trigger_reduce_call() -> None:
    adapter = _adapter(_content("merged content"))
    ext = _Extractor(adapter=adapter)
    out = await ext.reduce({"topic/a": ["frag one", "frag two"]}, {"filename": "d"})
    assert out == {"topic/a": "merged content"}
    sent = adapter.calls[0][0].stable
    assert "merge topic/a <= 30 file=d" in sent


# ---- max_chars bounding ----------------------------------------------------


def test_enforce_max_chars_bounds_every_section() -> None:
    ext = _Extractor(adapter=_adapter())
    bounded = ext._enforce_max_chars(
        {
            "topic/a": "y" * 100,  # cap 30
            "overview/summary": "z" * 100,  # cap 40
        }
    )
    assert len(bounded["topic/a"]) == 30
    assert len(bounded["overview/summary"]) == 40


async def test_reduce_output_respects_max_chars_even_if_model_overshoots() -> None:
    # The reduce model returns 100 chars for a section capped at 30; the final
    # guard in extract() must still bound it.
    adapter = _adapter(
        _map(**{"topic/a": "f1a", "topic/b": "f1b"}),  # chunk 1
        _map(**{"topic/a": "f2a", "topic/b": "f2b"}),  # chunk 2
        _content("q" * 100),  # reduce topic/a (2 frags -> merge); overshoots cap 30
        _content("q" * 100),  # reduce topic/b (2 frags -> merge); overshoots cap 30
    )
    ext = _Extractor(adapter=adapter)
    text = "\f".join([_page("p", 60), _page("p", 60)])  # 2 chunks -> 2 frags/section
    result = await ext.run(text.encode(), {"filename": "doc.pdf"})
    assert len(result.sections["topic/a"]) == 30
    assert len(result.sections["topic/b"]) == 30


# ---- End-to-end template (extract orchestration) ---------------------------


async def test_extract_runs_map_reduce_summarize_postprocess() -> None:
    adapter = _adapter(
        # map over two chunks
        _map(**{"topic/a": "a-frag-1"}),
        _map(**{"topic/a": "a-frag-2", "topic/b": "b-frag"}),
        # reduce topic/a (2 frags -> merge); topic/b is a single fitting frag (no call)
        _content("reduced A"),
    )
    ext = _Extractor(adapter=adapter)
    text = "\f".join([_page("p", 60), _page("p", 60)])
    result = await ext.run(text.encode(), {"filename": "doc.pdf"})

    assert result.sections["topic/a"] == "reduced A"
    assert result.sections["topic/b"] == "b-frag"
    # summarize() synthesized the required overview section from the reduced set.
    assert result.sections["overview/summary"].startswith("summary of:")
    # post_process() saw the filled sections and the title summarize() stashed.
    assert result.json_artifacts["coverage.json"] == {
        "a": True,
        "b": True,
        "title": "Derived Title",
    }
    # provenance hashes both prompts.
    assert result.meta["prompt_hash"] == ext._prompt_hash()


def test_prompt_hash_covers_both_prompts() -> None:
    a = _Extractor(adapter=_adapter())

    class _Other(_Extractor):
        REDUCE_PROMPT = "a different reduce prompt"

    b = _Other(adapter=_adapter())
    assert a._prompt_hash() != b._prompt_hash()


# ---- reduce() is the override seam -----------------------------------------


async def test_reduce_is_overridable_without_touching_map() -> None:
    class _WholeSetReduce(_Extractor):
        async def reduce(
            self, fragments_by_section: dict[str, list[str]], meta: dict[str, Any]
        ) -> dict[str, str]:
            # A single-pass strategy that ignores per-section model calls.
            return {name: " | ".join(frags) for name, frags in fragments_by_section.items()}

    adapter = _adapter(_map(**{"topic/a": "x", "topic/b": "y"}))
    ext = _WholeSetReduce(adapter=adapter)
    result = await ext.run(b"one page", {"filename": "doc.pdf"})
    assert result.sections["topic/a"] == "x"
    assert result.sections["topic/b"] == "y"
    assert adapter.remaining == 0  # only the single map call happened


# ---- Chunk-level map cache -------------------------------------------------


def _cached_extractor(cache_dir: Path, adapter: StubAdapter) -> _Extractor:
    """An `_Extractor` whose map cache is enabled at `cache_dir`."""

    class _Cached(_Extractor):
        pass

    _Cached.map_cache_dir = cache_dir
    return _Cached(adapter=adapter)


async def test_warm_cache_makes_zero_map_calls(tmp_path: Path) -> None:
    # The fixture is one chunk -> one map call; reduce makes no call (single
    # fragment fits), so the map call is the only model call in the run.
    raw, meta = b"one page", {"filename": "doc.pdf"}

    cold = _cached_extractor(tmp_path, _adapter(_map(**{"topic/a": "x"})))
    first = await cold.run(raw, meta)

    # Second run: an adapter with no canned responses — any model call raises.
    warm = _cached_extractor(tmp_path, _adapter())
    second = await warm.run(raw, meta)

    assert warm.adapter.calls == []  # every map call served from cache
    assert second.sections["topic/a"] == first.sections["topic/a"] == "x"


async def test_map_prompt_change_invalidates_cache(tmp_path: Path) -> None:
    raw, meta = b"one page", {"filename": "doc.pdf"}
    await _cached_extractor(tmp_path, _adapter(_map(**{"topic/a": "x"}))).run(raw, meta)

    class _NewMapPrompt(_Extractor):
        MAP_PROMPT = "DIFFERENT sections:\n{section_spec}\nfile={filename}"

    _NewMapPrompt.map_cache_dir = tmp_path
    changed = _NewMapPrompt(adapter=_adapter(_map(**{"topic/a": "y"})))
    await changed.run(raw, meta)

    assert len(changed.adapter.calls) == 1  # cache miss -> re-extracted


async def test_schema_version_change_invalidates_cache(tmp_path: Path) -> None:
    raw, meta = b"one page", {"filename": "doc.pdf"}
    await _cached_extractor(tmp_path, _adapter(_map(**{"topic/a": "x"}))).run(raw, meta)

    class _BumpedSchema(_Extractor):
        schema = _schema()

    _BumpedSchema.schema.version = "2"  # was the default "1"
    _BumpedSchema.map_cache_dir = tmp_path
    bumped = _BumpedSchema(adapter=_adapter(_map(**{"topic/a": "x"})))
    await bumped.run(raw, meta)

    assert len(bumped.adapter.calls) == 1  # cache miss -> re-extracted


async def test_cache_hit_adds_zero_tokens(tmp_path: Path) -> None:
    raw, meta = b"one page", {"filename": "doc.pdf"}

    cold = _cached_extractor(tmp_path, _adapter(_map(**{"topic/a": "x"})))
    first = await cold.run(raw, meta)
    assert first.meta["tokens_in"] == 10  # the one map call (StubAdapter usage)

    warm = _cached_extractor(tmp_path, _adapter())
    second = await warm.run(raw, meta)
    assert second.meta["tokens_in"] == 0  # hit -> no model call -> no tokens
    assert second.meta["tokens_out"] == 0


async def test_map_cache_disabled_by_default_is_noop(tmp_path: Path) -> None:
    ext = _Extractor(adapter=_adapter())
    assert ext.map_cache_dir is None
    key = ext._map_cache_key("prompt", "chunk")
    assert await ext.map_cache_get(key) is None
    await ext.map_cache_put(key, {"topic/a": "x"})  # no-op, must not raise
    assert list(tmp_path.iterdir()) == []  # nothing written anywhere


async def test_corrupt_cache_entry_is_treated_as_miss(tmp_path: Path) -> None:
    ext = _cached_extractor(tmp_path, _adapter())
    key = ext._map_cache_key("prompt", "chunk")
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / f"{key}.json").write_text("{ not valid json")
    assert await ext.map_cache_get(key) is None  # corrupt -> miss, not a crash
