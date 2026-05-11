from __future__ import annotations

import pytest

from reigner.artifacts.conventions import format_template, parse_template_keys


def test_parse_template_keys_in_order() -> None:
    assert parse_template_keys("{a}/{b}/{c}") == ("a", "b", "c")


def test_parse_template_keys_dedupes() -> None:
    assert parse_template_keys("{a}/{b}/{a}") == ("a", "b")


def test_parse_template_keys_no_placeholders() -> None:
    assert parse_template_keys("static/path") == ()


def test_format_template_fills_values() -> None:
    assert format_template("{a}/{b}", a="x", b="y") == "x/y"


def test_format_template_missing_raises() -> None:
    with pytest.raises(ValueError, match="missing placeholders"):
        format_template("{a}/{b}", a="x")


def test_format_template_extra_raises() -> None:
    with pytest.raises(ValueError, match="unexpected keys"):
        format_template("{a}", a="x", b="y")
