"""Unit tests for the chat renderer's summary heuristics.

Focus areas per AGENTS.md: bounded/self-describing outputs and truncation are
surfaced, and arg cleaning drops noise whole rather than clipping mid-token.
"""

from __future__ import annotations

from reigner.cli._tool_summary import clean_args, summarise


def test_summarise_counts_list_fields() -> None:
    assert summarise("bm25_search", {"hits": [1, 2, 3, 4, 5]}, truncated=False) == "5 hits"
    assert summarise("grep_artifact", {"matches": [1, 2, 3]}, truncated=False) == "3 matches"


def test_summarise_renders_size_and_content_bytes() -> None:
    assert summarise("get_section", {"size": 1843}, truncated=False) == "1.8 KB"
    # No explicit size key → derive from content length.
    assert summarise("read_artifact_file", {"content": "x" * 500}, truncated=False) == "500 B"


def test_summarise_surfaces_truncation_with_available_keys() -> None:
    out = summarise(
        "grep_artifact",
        {"matches": [1] * 5, "available_keys": ["matches"]},
        truncated=True,
    )
    assert out == "5 matches · truncated · +['matches']"


def test_summarise_has_more_flag() -> None:
    assert "more available" in summarise(
        "bm25_search", {"hits": [1], "has_more": True}, truncated=False
    )


def test_summarise_string_result_uses_bytes() -> None:
    assert summarise("x", "hello", truncated=False) == "5 B"


def test_summarise_unknown_shape_falls_back_to_ok() -> None:
    assert summarise("x", {"weird": True}, truncated=False) == "ok"
    assert summarise("x", None, truncated=False) == "ok"


def test_summarise_never_raises_on_odd_types() -> None:
    # A bool masquerading as a size must not be rendered as bytes.
    assert summarise("x", {"size": True}, truncated=False) == "ok"


def test_clean_args_drops_none_and_noise_defaults() -> None:
    out = clean_args({"file_path": None, "offset": 0, "limit": 4000})
    assert out == "limit=4000"


def test_clean_args_quotes_primary_subject() -> None:
    out = clean_args({"query": "supremacy of law", "top_k": 5})
    assert out == '"supremacy of law" · top_k=5'


def test_clean_args_clips_long_value_at_boundary_not_mid_token() -> None:
    out = clean_args({"query": "a" * 100})
    # Primary value clipped inside its quotes with a trailing ellipsis.
    assert out.startswith('"') and out.endswith('"')
    assert "…" in out
    assert len(out) <= 64
