"""Tests for EvalCase parsing and YAML loading (T-28)."""

from __future__ import annotations

import pytest

from reigner.eval.cases import EvalCase, load_cases


def test_from_dict_full() -> None:
    case = EvalCase.from_dict(
        {
            "id": "apple_rnd_2024",
            "query": "What were Apple's R&D expenses in 2024?",
            "expected_citations": ["AAPL/2024/metrics.json#field=research_and_development"],
            "forbidden_phrases": ["I think", "approximately"],
            "expected_clarification": False,
        }
    )
    assert case.id == "apple_rnd_2024"
    assert case.expected_citations == ["AAPL/2024/metrics.json#field=research_and_development"]
    assert case.forbidden_phrases == ["I think", "approximately"]
    assert case.expected_clarification is False


def test_from_dict_minimal_defaults() -> None:
    case = EvalCase.from_dict({"id": "c1", "query": "hello?"})
    assert case.expected_citations == []
    assert case.forbidden_phrases == []
    # Omitted clarification is tri-state None (assert nothing), not False.
    assert case.expected_clarification is None


def test_from_dict_missing_required() -> None:
    with pytest.raises(ValueError, match="missing required field"):
        EvalCase.from_dict({"query": "no id"})


def test_from_dict_unknown_field_rejected() -> None:
    with pytest.raises(ValueError, match="unknown field"):
        EvalCase.from_dict({"id": "c1", "query": "q", "forbidden_phrase": ["typo"]})


def test_from_dict_non_bool_clarification_rejected() -> None:
    with pytest.raises(ValueError, match="expected_clarification"):
        EvalCase.from_dict({"id": "c1", "query": "q", "expected_clarification": "yes"})


def test_load_cases_mapping_form(tmp_path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text(
        "cases:\n"
        "  - id: c1\n"
        "    query: first\n"
        "  - id: c2\n"
        "    query: second\n"
        "    expected_clarification: true\n"
    )
    cases = load_cases(path)
    assert [c.id for c in cases] == ["c1", "c2"]
    assert cases[1].expected_clarification is True


def test_load_cases_bare_list_form(tmp_path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text("- id: c1\n  query: only\n")
    cases = load_cases(path)
    assert len(cases) == 1
    assert cases[0].id == "c1"


def test_load_cases_empty_scaffold(tmp_path) -> None:
    # Matches the `reigner init` scaffold: `cases: []`.
    path = tmp_path / "cases.yaml"
    path.write_text("cases: []\n")
    assert load_cases(path) == []


def test_load_cases_rejects_wrong_top_level(tmp_path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text("just a string\n")
    with pytest.raises(ValueError, match="mapping with a 'cases:' list"):
        load_cases(path)
