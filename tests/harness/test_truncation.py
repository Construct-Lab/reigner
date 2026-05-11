"""Unit tests for truncate_for_tool (T-05 / issue #5)."""

from __future__ import annotations

import json

from reigner.harness.truncation import truncate_for_tool


def test_under_budget_pass_through() -> None:
    out, was_truncated = truncate_for_tool({"a": 1}, char_limit=1000)
    assert out == {"a": 1}
    assert was_truncated is False


def test_string_truncated_with_marker() -> None:
    out, was_truncated = truncate_for_tool("x" * 500, char_limit=50)
    assert was_truncated is True
    assert isinstance(out, str)
    assert out.endswith("[truncated]")
    assert len(out) <= 50


def test_list_keeps_prefix_and_announces_truncation() -> None:
    big = [{"i": i, "padding": "x" * 100} for i in range(50)]
    out, was_truncated = truncate_for_tool(big, char_limit=300)
    assert was_truncated is True
    assert isinstance(out, dict)
    assert out["_truncated"] is True
    assert out["_original_count"] == 50
    assert isinstance(out["items"], list)
    assert len(out["items"]) < 50
    # Serialized payload respects the cap.
    assert len(json.dumps(out)) <= 300 + 1


def test_dict_keeps_prefix_and_marks() -> None:
    big = {f"k{i}": "x" * 100 for i in range(50)}
    out, was_truncated = truncate_for_tool(big, char_limit=400)
    assert was_truncated is True
    assert isinstance(out, dict)
    assert out["_truncated"] is True
    assert "_original_keys" in out
    assert len(out["_original_keys"]) == 50


def test_zero_limit_disables_truncation() -> None:
    out, was_truncated = truncate_for_tool({"a": "long"}, char_limit=0)
    assert was_truncated is False
    assert out == {"a": "long"}
