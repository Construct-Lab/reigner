"""PiiRedactPlugin: recursive scrub, structure preservation, fail-loud (SPEC §12)."""

from __future__ import annotations

import re

import pytest

from reigner.harness.events import FinalAnswerEvent, ToolResultEvent
from reigner.plugins.pii_redact import DEFAULT_TOKEN, PiiRedactPlugin

SSN = r"\b\d{3}-\d{2}-\d{4}\b"
EMAIL = r"[\w.+-]+@[\w-]+\.[\w.-]+"


def _result(payload: object) -> ToolResultEvent:
    return ToolResultEvent(
        seq=1,
        session_id="s",
        turn=0,
        call_id="c1",
        result=payload,
        truncated=False,
        cached=False,
    )


def _redactor() -> PiiRedactPlugin:
    return PiiRedactPlugin(patterns=[SSN, EMAIL])


async def test_scrubs_nested_payload_and_preserves_structure() -> None:
    event = _result(
        {
            "rows": [
                {"name": "A. Patel", "email": "ap@acme.com", "ssn": "412-55-0190"},
            ],
            "count": 1,
            "has_more": False,
        }
    )
    out = await _redactor().after_tool_call(call=None, result=event, state=None)  # type: ignore[arg-type]

    row = out.result["rows"][0]
    assert row["email"] == DEFAULT_TOKEN
    assert row["ssn"] == DEFAULT_TOKEN
    assert row["name"] == "A. Patel"  # no pattern matched — untouched
    assert out.result["count"] == 1  # ints pass through, not stringified
    assert out.result["has_more"] is False  # bools pass through
    assert list(out.result.keys()) == ["rows", "count", "has_more"]  # keys intact


async def test_envelope_fields_are_carried_through() -> None:
    event = _result({"v": "x@y.io"})
    out = await _redactor().after_tool_call(call=None, result=event, state=None)  # type: ignore[arg-type]
    assert out.call_id == "c1"
    assert out.truncated is False
    assert out.cached is False
    assert out is not event  # a new event, original not mutated
    assert event.result == {"v": "x@y.io"}


async def test_scrubs_final_answer_text() -> None:
    answer = FinalAnswerEvent(
        seq=2, session_id="s", turn=0, text="Reach me at a@b.com or 412-55-0190.", metadata={}
    )
    out = await _redactor().on_final_answer(answer=answer, state=None)  # type: ignore[arg-type]
    assert "a@b.com" not in out.text
    assert "412-55-0190" not in out.text
    assert out.text.count(DEFAULT_TOKEN) == 2


async def test_custom_token() -> None:
    plugin = PiiRedactPlugin(patterns=[EMAIL], token="<pii>")
    out = await plugin.after_tool_call(call=None, result=_result("ping x@y.io"), state=None)  # type: ignore[arg-type]
    assert out.result == "ping <pii>"


async def test_accepts_precompiled_pattern() -> None:
    plugin = PiiRedactPlugin(patterns=[re.compile(EMAIL)])
    out = await plugin.after_tool_call(call=None, result=_result("x@y.io"), state=None)  # type: ignore[arg-type]
    assert out.result == DEFAULT_TOKEN


def test_bad_pattern_fails_loud_at_construction() -> None:
    with pytest.raises(re.error):
        PiiRedactPlugin(patterns=["("])  # unbalanced paren — never silently ignored
