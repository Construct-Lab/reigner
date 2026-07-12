"""Unit tests for the five built-in eval checks (SPEC §15.1).

Checks are pure functions over a :class:`CaseRun`, so these tests construct run
records by hand — no live harness, no model calls. Each check is exercised on
its pass / fail / na paths, plus one end-to-end scorecard render with all five
columns.
"""

from __future__ import annotations

from reigner.eval.cases import EvalCase
from reigner.eval.checks import CaseRun, registered_checks
from reigner.eval.coverage import coverage
from reigner.eval.entity_resolution import entity_resolution
from reigner.eval.faithfulness import faithfulness
from reigner.eval.latency_cost import latency_cost
from reigner.eval.repeated_calls import repeated_calls
from reigner.eval.runner import CaseResult, SuiteResult, render_scorecard
from reigner.harness.events import (
    ClarificationEvent,
    Event,
    FinalAnswerEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from reigner.tools.provenance.lineage import Citation

# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def _final(text: str) -> FinalAnswerEvent:
    return FinalAnswerEvent(seq=0, session_id="s", turn=0, text=text, metadata={})


def _tool_call(name: str, args: dict[str, object], seq: int = 0) -> ToolCallEvent:
    return ToolCallEvent(seq=seq, session_id="s", turn=0, name=name, args=args, call_id=f"c{seq}")


def _tool_result(result: object, seq: int = 1) -> ToolResultEvent:
    return ToolResultEvent(
        seq=seq,
        session_id="s",
        turn=0,
        call_id=f"c{seq}",
        result=result,
        truncated=False,
        cached=False,
    )


def _clarification() -> ClarificationEvent:
    return ClarificationEvent(
        seq=0, session_id="s", turn=0, question="Which company?", candidates=["AAPL", "MSFT"]
    )


def _citation(value: object, source: str = "AAPL/2024/metrics.json") -> Citation:
    return Citation(source=source, locator={"field": "rnd"}, value=value, turn=0)


def _run(
    *,
    text: str | None = None,
    events: list[Event] | None = None,
    citations: list[Citation] | None = None,
    elapsed: float = 0.0,
    usage: dict[str, object] | None = None,
) -> CaseRun:
    final = _final(text) if text is not None else None
    return CaseRun(
        final=final,
        events=list(events or []),
        citations=list(citations or []),
        elapsed=elapsed,
        usage=dict(usage or {}),
    )


def _case(**kwargs: object) -> EvalCase:
    return EvalCase(id="c", query="q", **kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


def test_all_five_checks_register() -> None:
    names = registered_checks()
    for expected in (
        "faithfulness",
        "repeated_calls",
        "entity_resolution",
        "coverage",
        "latency_cost",
    ):
        assert expected in names


# --------------------------------------------------------------------------- #
# faithfulness
# --------------------------------------------------------------------------- #


def test_faithfulness_passes_with_scale_normalized_citation() -> None:
    run = _run(text="Apple's R&D was $31.4B.", citations=[_citation(31_400_000_000)])
    assert faithfulness(_case(), run).status == "pass"


def test_faithfulness_tolerates_citation_stored_in_billions() -> None:
    # Answer says "31.4 billion"; citation stores the bare 31.4.
    run = _run(text="R&D was $31.4 billion.", citations=[_citation(31.4)])
    assert faithfulness(_case(), run).status == "pass"


def test_faithfulness_fails_on_uncited_number() -> None:
    run = _run(text="Buybacks were $67B.", citations=[])
    result = faithfulness(_case(), run)
    assert result.status == "fail"
    assert "not cited" in result.detail


def test_faithfulness_na_when_no_numeric_claims() -> None:
    run = _run(text="Revenue grew across all segments.", citations=[])
    assert faithfulness(_case(), run).status == "na"


def test_faithfulness_ignores_calendar_years() -> None:
    # 2024 is a year, not a citable metric; only $31.4B needs a citation.
    run = _run(text="In 2024, R&D was $31.4B.", citations=[_citation(31_400_000_000)])
    assert faithfulness(_case(), run).status == "pass"


def test_faithfulness_ignores_fiscal_year_ranges() -> None:
    # A year range must not leak its trailing token as a number; only 694 is a
    # claim. Covers ASCII hyphen, slash, and the en-dash prose models emit.
    for span in ("2022-23", "2022/2023", "2022–23"):
        run = _run(
            text=f"IIT Madras ran 694 sponsored projects in {span}.",
            citations=[_citation(694)],
        )
        assert faithfulness(_case(), run).status == "pass", span


def test_faithfulness_reads_markdown_bolded_numbers() -> None:
    # Models routinely bold the figure ("**1,234**"); it must still be verified.
    run = _run(text="The total was **1,234 units**.", citations=[_citation(1234)])
    assert faithfulness(_case(), run).status == "pass"

    uncited = _run(text="The total was **1,235 units**.", citations=[_citation(1234)])
    assert faithfulness(_case(), uncited).status == "fail"


def test_faithfulness_ignores_digits_inside_identifiers() -> None:
    # "SKU-0497" must not yield the phantom claim -497 / 497; only 325 counts.
    run = _run(
        text="Record SKU-0497 lists 325 units in stock.",
        citations=[_citation(325)],
    )
    assert faithfulness(_case(), run).status == "pass"


# --------------------------------------------------------------------------- #
# repeated_calls
# --------------------------------------------------------------------------- #


def test_repeated_calls_fails_on_identical_call() -> None:
    args = {"path": "AAPL/2024/metrics.json"}
    run = _run(
        events=[
            _tool_call("read_artifact_file", args, seq=0),
            _tool_call("read_artifact_file", dict(args), seq=1),
        ]
    )
    result = repeated_calls(_case(), run)
    assert result.status == "fail"
    assert "2×" in result.detail


def test_repeated_calls_passes_when_all_unique() -> None:
    run = _run(
        events=[
            _tool_call("read_artifact_file", {"path": "a.json"}, seq=0),
            _tool_call("read_artifact_file", {"path": "b.json"}, seq=1),
        ]
    )
    assert repeated_calls(_case(), run).status == "pass"


def test_repeated_calls_na_without_tool_calls() -> None:
    run = _run(text="done")
    assert repeated_calls(_case(), run).status == "na"


# --------------------------------------------------------------------------- #
# entity_resolution
# --------------------------------------------------------------------------- #


def test_entity_resolution_passes_when_ambiguous_case_clarified() -> None:
    run = _run(events=[_clarification()])
    result = entity_resolution(_case(expected_clarification=True), run)
    assert result.status == "pass"
    assert result.detail == "clarified"


def test_entity_resolution_fails_when_ambiguous_case_guessed() -> None:
    run = _run(text="It was $383B.")
    assert entity_resolution(_case(expected_clarification=True), run).status == "fail"


def test_entity_resolution_na_when_not_ambiguous() -> None:
    run = _run(text="answer")
    assert entity_resolution(_case(expected_clarification=None), run).status == "na"
    assert entity_resolution(_case(expected_clarification=False), run).status == "na"


# --------------------------------------------------------------------------- #
# coverage
# --------------------------------------------------------------------------- #


def test_coverage_passes_on_exact_retrieval() -> None:
    run = _run(events=[_tool_call("read_artifact_file", {"path": "AAPL/2024/metrics.json"})])
    case = _case(expected_citations=["AAPL/2024/metrics.json#field=rnd"])
    assert coverage(case, run).status == "pass"


def test_coverage_passes_on_directory_prefix_retrieval() -> None:
    run = _run(events=[_tool_call("grep_artifact", {"file_path": "AAPL/2024"})])
    case = _case(expected_citations=["AAPL/2024/metrics.json#field=rnd"])
    assert coverage(case, run).status == "pass"


def test_coverage_passes_on_entity_scoped_grep() -> None:
    # grep_artifact(entity="AAPL/2024") names the scope via ``entity``, not a
    # path arg; the prefix match should still cover a source under it.
    run = _run(events=[_tool_call("grep_artifact", {"query": "R&D", "entity": "AAPL/2024"})])
    case = _case(expected_citations=["AAPL/2024/sections/risk_factors#para=3"])
    assert coverage(case, run).status == "pass"


def test_coverage_passes_on_get_section_result_path() -> None:
    # get_section carries the resolved path only in its result, not its args.
    events = [
        _tool_call("get_section", {"section": "risk_factors", "ticker": "AAPL", "year": "2024"}),
        _tool_result({"section": "risk_factors", "path": "AAPL/2024/sections/risk_factors"}),
    ]
    run = _run(events=events)
    case = _case(expected_citations=["AAPL/2024/sections/risk_factors#para=3"])
    assert coverage(case, run).status == "pass"


def test_coverage_fails_and_lists_uncovered_sources() -> None:
    run = _run(events=[_tool_call("read_artifact_file", {"path": "AAPL/2024/metrics.json"})])
    case = _case(expected_citations=["MSFT/2023/metrics.json#field=buyback"])
    result = coverage(case, run)
    assert result.status == "fail"
    assert "MSFT/2023/metrics.json" in result.detail


def test_coverage_na_without_expected_citations() -> None:
    assert coverage(_case(), _run(text="x")).status == "na"


# --------------------------------------------------------------------------- #
# latency_cost
# --------------------------------------------------------------------------- #


def test_latency_cost_reports_tokens_and_seconds() -> None:
    run = _run(text="x", elapsed=1.2, usage={"total": 8100})
    result = latency_cost(_case(), run)
    assert result.status == "pass"
    assert result.detail == "8.1k tok · 1.2s"


def test_latency_cost_fails_over_token_budget() -> None:
    run = _run(text="x", elapsed=0.4, usage={"total": 6420})
    result = latency_cost(_case(max_tokens=6000), run)
    assert result.status == "fail"
    assert "max_tokens" in result.detail


def test_latency_cost_fails_over_time_budget() -> None:
    run = _run(text="x", elapsed=9.0, usage={"total": 100})
    result = latency_cost(_case(max_seconds=5.0), run)
    assert result.status == "fail"
    assert "max_seconds" in result.detail


def test_latency_cost_falls_back_to_prompt_plus_completion() -> None:
    run = _run(text="x", elapsed=0.1, usage={"prompt": 200, "completion": 50})
    result = latency_cost(_case(), run)
    assert result.status == "pass"
    assert result.detail.startswith("250 tok")


# --------------------------------------------------------------------------- #
# Scorecard render with all five columns
# --------------------------------------------------------------------------- #


def test_scorecard_renders_all_five_columns() -> None:
    case = _case(expected_citations=["MSFT/2023/metrics.json#field=buyback"])
    run = _run(text="Buybacks were $67B.", elapsed=0.4, usage={"total": 6420})
    results = [
        faithfulness(case, run),
        repeated_calls(case, run),
        entity_resolution(case, run),
        coverage(case, run),
        latency_cost(case, run),
    ]
    suite = SuiteResult(cases=[CaseResult(case=case, run=run, results=results)])
    out = render_scorecard(suite, date="2026-06-16")

    for name in ("faithfulness", "repeated_calls", "entity_resolution", "coverage", "latency_cost"):
        assert name in out
    assert "✗" in out  # faithfulness + coverage both fail this case
    assert "0 passed · 1 failed" in out
