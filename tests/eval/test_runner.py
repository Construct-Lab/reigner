"""End-to-end tests for EvalSuite.run and the two-tier evaluation.

Uses a stub adapter so runs are deterministic and free. Named checks are
registered with the real ``@check`` decorator against a per-test snapshot of
the registry, so these tests never leak into (or depend on) the built-in checks.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

import reigner.eval.checks as checks_mod
from reigner.config import SessionsConfig, SettingsConfig
from reigner.eval.cases import EvalCase
from reigner.eval.checks import CaseRun, CheckResult, check
from reigner.eval.runner import EvalSuite
from reigner.harness.adapters.base import ModelAction, TokenUsage, ToolCall
from reigner.harness.agent import Harness
from reigner.harness.events import FinalAnswerEvent
from reigner.harness.state import Prompt
from reigner.tools.registry import ToolRegistry


@dataclass
class FakeAdapter:
    """Returns a queued ModelAction per call; optionally raises to mimic failure."""

    name: str = "fake"
    model: str = "fake-1"
    supports_prompt_caching: bool = False
    actions: list[ModelAction] = field(default_factory=list)
    calls: list[Prompt] = field(default_factory=list)
    raise_on_call: bool = False

    async def call(self, prompt: Prompt, tools: list[Any]) -> ModelAction:
        self.calls.append(prompt)
        if self.raise_on_call:
            raise RuntimeError("adapter boom")
        return self.actions.pop(0)


def _final(text: str) -> ModelAction:
    return ModelAction(
        is_final_answer=True,
        text=text,
        tool_calls=[],
        usage=TokenUsage.empty(),
        stop_reason="end_turn",
    )


def _clarify() -> ModelAction:
    return ModelAction(
        is_final_answer=False,
        text=None,
        tool_calls=[
            ToolCall(
                id="c1",
                name="request_clarification",
                args={"question": "Which company?", "candidates": ["AAPL", "MSFT"]},
            )
        ],
        usage=TokenUsage.empty(),
        stop_reason="tool_calls",
    )


def _harness(adapter: FakeAdapter) -> Harness:
    return Harness(
        adapter=adapter,
        registry=ToolRegistry(),
        role="ROLE",
        settings=SettingsConfig(),
        sessions=SessionsConfig(auto_save=False),
    )


@pytest.fixture(autouse=True)
def clean_registry() -> Iterator[None]:
    """Snapshot and restore the global check registry around each test."""
    saved = dict(checks_mod._REGISTRY)
    try:
        yield
    finally:
        checks_mod._REGISTRY.clear()
        checks_mod._REGISTRY.update(saved)


async def test_passing_case_runs_intrinsic_and_named() -> None:
    @check("always_pass")
    async def always_pass(case: EvalCase, run: CaseRun) -> CheckResult:
        assert run.answered
        return CheckResult("always_pass", "pass")

    adapter = FakeAdapter(actions=[_final("Apple's R&D was $31.4B.")])
    suite = EvalSuite(
        [
            EvalCase(id="apple", query="rnd?", forbidden_phrases=["I think"]),
        ]
    )
    result = await suite.run(_harness(adapter), checks=["always_pass"])

    assert result.passed
    case = result.cases[0]
    names = {r.name: r.status for r in case.results}
    assert names == {"forbidden_phrases": "pass", "always_pass": "pass"}


async def test_forbidden_phrase_fails_case() -> None:
    adapter = FakeAdapter(actions=[_final("I think it was approximately $30B.")])
    suite = EvalSuite([EvalCase(id="c", query="q", forbidden_phrases=["I think"])])
    result = await suite.run(_harness(adapter))

    case = result.cases[0]
    forbidden = next(r for r in case.results if r.name == "forbidden_phrases")
    assert forbidden.status == "fail"
    assert "I think" in forbidden.detail
    assert not case.passed
    assert not result.passed


async def test_expected_clarification_pass_via_real_event() -> None:
    # The loop intercepts request_clarification by name regardless of profile,
    # so the stub can drive a real ClarificationEvent.
    adapter = FakeAdapter(actions=[_clarify()])
    suite = EvalSuite([EvalCase(id="ambiguous", query="revenue?", expected_clarification=True)])
    result = await suite.run(_harness(adapter))

    case = result.cases[0]
    clar = next(r for r in case.results if r.name == "expected_clarification")
    assert clar.status == "pass"
    assert clar.detail == "clarified"
    assert case.run.final is None  # clarification ends the round without an answer
    assert case.passed


async def test_expected_clarification_mismatch_fails() -> None:
    adapter = FakeAdapter(actions=[_final("It was $383B.")])
    suite = EvalSuite([EvalCase(id="ambiguous", query="revenue?", expected_clarification=True)])
    result = await suite.run(_harness(adapter))

    clar = next(r for r in result.cases[0].results if r.name == "expected_clarification")
    assert clar.status == "fail"
    assert not result.cases[0].passed


async def test_na_status_does_not_fail_case() -> None:
    @check("na_check")
    def na_check(case: EvalCase, run: CaseRun) -> CheckResult:
        return CheckResult("na_check", "na", "not applicable")

    adapter = FakeAdapter(actions=[_final("answer")])
    suite = EvalSuite([EvalCase(id="c", query="q")])
    result = await suite.run(_harness(adapter), checks=["na_check"])

    assert result.cases[0].results[0].status == "na"
    assert result.cases[0].passed
    assert result.passed


async def test_sync_and_async_checks_both_run() -> None:
    @check("sync_one")
    def sync_one(case: EvalCase, run: CaseRun) -> CheckResult:
        return CheckResult("sync_one", "pass")

    @check("async_one")
    async def async_one(case: EvalCase, run: CaseRun) -> CheckResult:
        return CheckResult("async_one", "fail", "nope")

    adapter = FakeAdapter(actions=[_final("answer")])
    suite = EvalSuite([EvalCase(id="c", query="q")])
    result = await suite.run(_harness(adapter), checks=["sync_one", "async_one"])

    statuses = {r.name: r.status for r in result.cases[0].results}
    assert statuses == {"sync_one": "pass", "async_one": "fail"}


async def test_unknown_check_raises_before_running() -> None:
    adapter = FakeAdapter(actions=[_final("answer")])
    suite = EvalSuite([EvalCase(id="c", query="q")])
    with pytest.raises(KeyError, match="unknown eval check 'nope'"):
        await suite.run(_harness(adapter), checks=["nope"])
    # Fail-fast: no model call was made.
    assert adapter.calls == []


async def test_suite_never_aborts_on_exception() -> None:
    # First case's adapter raises; the suite must still run and report it,
    # and a second, independent case must still complete.
    boom = _harness(FakeAdapter(raise_on_call=True))
    ok = _harness(FakeAdapter(actions=[_final("fine")]))

    suite = EvalSuite([EvalCase(id="boom", query="q")])
    boom_result = await suite.run(boom)
    boom_case = boom_result.cases[0]
    assert boom_case.run.final is None
    assert any(type(e).__name__ == "ErrorEvent" for e in boom_case.run.events)

    ok_result = await EvalSuite([EvalCase(id="ok", query="q")]).run(ok)
    assert ok_result.cases[0].run.answered


async def test_fresh_session_per_case_no_state_leak() -> None:
    # Two cases on one harness must not share citations/history.
    adapter = FakeAdapter(actions=[_final("a"), _final("b")])
    suite = EvalSuite([EvalCase(id="c1", query="q1"), EvalCase(id="c2", query="q2")])
    result = await suite.run(_harness(adapter))

    assert len(result.cases) == 2
    assert isinstance(result.cases[0].run.final, FinalAnswerEvent)
    assert result.cases[0].run.final.text == "a"
    assert result.cases[1].run.final.text == "b"
