from __future__ import annotations

import pytest

from reigner.tools.search.filters import FilterError, matches, parse_filters


def test_parse_none_yields_empty_filter() -> None:
    assert parse_filters(None) == {}


def test_parse_empty_dict_yields_empty_filter() -> None:
    assert parse_filters({}) == {}


def test_parse_scalar_and_list_values() -> None:
    out = parse_filters({"entity_id": "AAPL", "year": ["2023", "2024"]})
    assert out == {"entity_id": "AAPL", "year": ["2023", "2024"]}


def test_parse_rejects_non_dict() -> None:
    with pytest.raises(FilterError):
        parse_filters("entity_id=AAPL")  # type: ignore[arg-type]


def test_parse_rejects_empty_key() -> None:
    with pytest.raises(FilterError):
        parse_filters({"": "x"})


def test_parse_rejects_non_string_list_member() -> None:
    with pytest.raises(FilterError):
        parse_filters({"year": ["2024", 2025]})  # type: ignore[list-item]


def test_parse_rejects_empty_list() -> None:
    with pytest.raises(FilterError):
        parse_filters({"year": []})


def test_parse_rejects_unsupported_value_type() -> None:
    with pytest.raises(FilterError):
        parse_filters({"year": 2024})  # type: ignore[dict-item]


def test_matches_scalar_exact() -> None:
    assert matches({"entity_id": "AAPL"}, {"entity_id": "AAPL"})
    assert not matches({"entity_id": "MSFT"}, {"entity_id": "AAPL"})


def test_matches_list_is_or_within_key() -> None:
    assert matches({"year": "2024"}, {"year": ["2023", "2024"]})
    assert not matches({"year": "2022"}, {"year": ["2023", "2024"]})


def test_matches_multiple_keys_are_anded() -> None:
    ids = {"entity_id": "AAPL", "year": "2024"}
    assert matches(ids, {"entity_id": "AAPL", "year": "2024"})
    assert not matches(ids, {"entity_id": "AAPL", "year": "2023"})


def test_matches_missing_identifier_is_a_miss() -> None:
    assert not matches({"entity_id": "AAPL"}, {"year": "2024"})


def test_matches_empty_filter_matches_anything() -> None:
    assert matches({"entity_id": "AAPL"}, {})
    assert matches({}, {})
