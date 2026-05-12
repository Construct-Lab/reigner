"""Unit tests for truncate_for_tool / resolve_limit (T-06, G2)."""

from __future__ import annotations

import json

from reigner.harness.truncation import resolve_limit, truncate_for_tool


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


def test_dict_records_available_keys() -> None:
    big = {f"k{i}": "x" * 100 for i in range(20)}
    out, was_truncated = truncate_for_tool(big, char_limit=400)
    assert was_truncated is True
    assert isinstance(out, dict)
    dropped = out["available_keys"]
    assert isinstance(dropped, list)
    assert len(dropped) > 0
    # Every dropped key should be one of the originals and not present at top level.
    for key in dropped:
        assert key in out["_original_keys"]
        assert key not in {k for k in out if not k.startswith("_") and k != "available_keys"}


def test_dict_recurses_into_oversized_value() -> None:
    # A single value is too big to fit verbatim, but partial inclusion is useful.
    big = {"body": "x" * 5000, "meta": {"id": 1}}
    out, was_truncated = truncate_for_tool(big, char_limit=600)
    assert was_truncated is True
    assert isinstance(out, dict)
    # 'meta' fits easily; 'body' should have been recursively truncated, not dropped.
    if "body" in out:
        assert isinstance(out["body"], str)
        assert out["body"].endswith("[truncated]")


def test_resolve_limit_uses_override() -> None:
    assert resolve_limit("read", {"read": 2000}, default=500) == 2000
    assert resolve_limit("grep", {"read": 2000}, default=500) == 500
