"""Per-run token/cost accounting must be isolated across concurrent runs.

The pipeline shares one extractor instance across documents and runs each in its
own task. Before this fix the running token tally lived on the instance, so a
second document's ``run()`` (which reset the tally at its start and read it at
its end) could clobber a first document's mid-flight totals. These tests drive
two ``run()`` calls concurrently on a *single shared* extractor and assert each
reports only its own model calls.
"""

from __future__ import annotations

import asyncio
from typing import Any

from reigner.artifacts import ArtifactSchema, JsonArtifactSpec, SectionSpec
from reigner.harness.adapters.base import TokenUsage
from reigner.ingestion import ExtractionResult, LLMExtractor
from tests.ingestion.conftest import StubAdapter, make_response


def _schema() -> ArtifactSchema:
    return ArtifactSchema(
        entity_path="{ticker}/{fiscal_year}",
        sections=[SectionSpec(name="document_summary", required=True)],
        json_artifacts=[
            JsonArtifactSpec(name="metadata.json", fields={"ticker": str, "fiscal_year": int}),
        ],
    )


class _NCallExtractor(LLMExtractor):
    """Calls the model ``meta["n_calls"]`` times, yielding between calls.

    The ``sleep(0)`` hands control back to the event loop between calls so two
    concurrent runs genuinely interleave — the exact window in which shared
    instance state would race.
    """

    schema = _schema()
    PROMPT = "extract"
    base_backoff_seconds = 0.0

    async def extract(self, raw: bytes, meta: dict[str, Any]) -> ExtractionResult:
        parsed: dict[str, Any] = {}
        for _ in range(meta["n_calls"]):
            parsed = await self.call_model(prompt=self.PROMPT, input_text="x")
            await asyncio.sleep(0)
        return ExtractionResult(
            sections=parsed["sections"],
            json_artifacts=parsed["json_artifacts"],
        )


def _good() -> str:
    return make_response(
        sections={"document_summary": "ok"},
        json_artifacts={"metadata.json": {"ticker": "AAPL", "fiscal_year": 2024}},
    )


async def test_concurrent_runs_isolate_token_totals() -> None:
    # One run does 1 model call, the other does 3; each call reports 10/20.
    # Isolated totals: (10, 20) and (30, 60). A shared tally would mix them.
    adapter = StubAdapter(
        responses=[_good()] * 4,
        usage=TokenUsage(prompt=10, completion=20, total=30),
    )
    extractor = _NCallExtractor(adapter=adapter)  # ONE instance, shared below

    a, b = await asyncio.gather(
        extractor.run(raw=b"a", meta={"ticker": "A", "fiscal_year": 2024, "n_calls": 1}),
        extractor.run(raw=b"b", meta={"ticker": "B", "fiscal_year": 2024, "n_calls": 3}),
    )

    assert (a.meta["tokens_in"], a.meta["tokens_out"]) == (10, 20)
    assert (b.meta["tokens_in"], b.meta["tokens_out"]) == (30, 60)


async def test_concurrent_runs_isolate_cost() -> None:
    class _Priced(_NCallExtractor):
        pricing = {"stub:stub-model": {"input": 1000.0, "output": 2000.0}}

    adapter = StubAdapter(
        responses=[_good()] * 4,
        usage=TokenUsage(prompt=10, completion=20, total=30),
    )
    extractor = _Priced(adapter=adapter)

    a, b = await asyncio.gather(
        extractor.run(raw=b"a", meta={"ticker": "A", "fiscal_year": 2024, "n_calls": 1}),
        extractor.run(raw=b"b", meta={"ticker": "B", "fiscal_year": 2024, "n_calls": 3}),
    )

    # per call: 1000 * 10/1e6 + 2000 * 20/1e6 = 0.01 + 0.04 = 0.05
    assert a.meta["cost_usd"] == 0.05
    assert b.meta["cost_usd"] == 0.15


async def test_call_model_outside_run_does_not_crash() -> None:
    # No run() active ⇒ the ContextVar is unset (default None); call_model must
    # still return normally, just without accumulating anywhere.
    adapter = StubAdapter(
        responses=[_good()],
        usage=TokenUsage(prompt=10, completion=20, total=30),
    )
    extractor = _NCallExtractor(adapter=adapter)
    parsed = await extractor.call_model(prompt="p", input_text="x")
    assert parsed["sections"] == {"document_summary": "ok"}
