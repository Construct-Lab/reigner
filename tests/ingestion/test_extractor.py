from __future__ import annotations

import sys
from typing import Any

import pytest

from reigner.artifacts import ArtifactSchema, JsonArtifactSpec, SectionSpec
from reigner.harness.adapters.base import (
    AdapterAuthError,
    TokenUsage,
    TransientAdapterError,
)
from reigner.ingestion import (
    ExtractionError,
    ExtractionResult,
    LLMExtractor,
    TransientError,
    ValidationError,
    resolve_adapter,
)
from tests.ingestion.conftest import StubAdapter, make_response


def _basic_schema() -> ArtifactSchema:
    return ArtifactSchema(
        entity_path="{ticker}/{fiscal_year}",
        sections=[
            SectionSpec(name="document_summary", required=True),
            SectionSpec(name="sections/business"),
        ],
        json_artifacts=[
            JsonArtifactSpec(
                name="metadata.json",
                fields={"ticker": str, "fiscal_year": int},
            ),
        ],
    )


class _Extractor(LLMExtractor):
    """A minimal subclass used by every test below.

    The default `extract()` calls the model once with `PROMPT` and parses the
    response shape `{sections, json_artifacts}` into an ExtractionResult.
    """

    schema = _basic_schema()
    PROMPT = "Extract the SEC 10-K into JSON matching the provided schema."
    base_backoff_seconds = 0.0  # tests don't wait

    async def extract(self, raw: bytes, meta: dict[str, Any]) -> ExtractionResult:
        parsed = await self.call_model(prompt=self.PROMPT, input_text=raw.decode())
        return ExtractionResult(
            sections=parsed.get("sections", {}),
            json_artifacts=parsed.get("json_artifacts", {}),
        )


# ---- Adapter resolver -----------------------------------------------------


def test_resolve_adapter_dispatches_anthropic() -> None:
    pytest.importorskip("anthropic")
    adapter = resolve_adapter("anthropic:claude-opus-4-7")
    assert adapter.name == "anthropic"
    assert adapter.model == "claude-opus-4-7"


def test_resolve_adapter_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="unknown provider"):
        resolve_adapter("nope:foo")


def test_resolve_adapter_requires_provider_prefix() -> None:
    with pytest.raises(ValueError, match="provider:model_id"):
        resolve_adapter("claude-opus-4-7")


# ---- Happy path -----------------------------------------------------------


async def test_happy_path_run_returns_validated_result() -> None:
    adapter = StubAdapter(
        responses=[
            make_response(
                sections={
                    "document_summary": "Apple FY24 summary.",
                    "sections/business": "Hardware + services.",
                },
                json_artifacts={
                    "metadata.json": {"ticker": "AAPL", "fiscal_year": 2024},
                },
            ),
        ],
    )
    extractor = _Extractor(adapter=adapter)

    result = await extractor.run(raw=b"raw-pdf-bytes", meta={"ticker": "AAPL"})

    assert result.sections["document_summary"] == "Apple FY24 summary."
    assert result.json_artifacts["metadata.json"]["fiscal_year"] == 2024
    # provenance stamped
    assert result.meta["schema_version"] == "1"
    assert result.meta["model"] == "stub:stub-model"
    assert result.meta["tokens_in"] == 10
    assert result.meta["tokens_out"] == 20
    assert result.meta["cost_usd"] == 0.0
    assert len(result.meta["source_hash"]) == 64  # sha256 hex
    assert len(result.meta["prompt_hash"]) == 64
    assert len(adapter.calls) == 1


async def test_run_uses_no_tools_and_passes_input_as_user_turn() -> None:
    adapter = StubAdapter(
        responses=[
            make_response(
                sections={"document_summary": "ok"},
                json_artifacts={
                    "metadata.json": {"ticker": "AAPL", "fiscal_year": 2024},
                },
            ),
        ],
    )
    extractor = _Extractor(adapter=adapter)
    await extractor.run(raw=b"the input text", meta={})

    prompt, tools = adapter.calls[0]
    assert tools == []
    assert prompt.stable == _Extractor.PROMPT
    assert len(prompt.messages) == 1
    assert prompt.messages[0].role == "user"
    assert prompt.messages[0].content == "the input text"


# ---- JSON parsing ---------------------------------------------------------


async def test_markdown_fenced_json_is_stripped() -> None:
    fenced = (
        "```json\n"
        '{"sections": {"document_summary": "ok"},'
        ' "json_artifacts": {"metadata.json": {"ticker": "AAPL", "fiscal_year": 2024}}}\n'
        "```"
    )
    adapter = StubAdapter(responses=[fenced])
    extractor = _Extractor(adapter=adapter)
    result = await extractor.run(raw=b"x", meta={})
    assert result.sections["document_summary"] == "ok"


async def test_non_json_response_raises_extraction_error() -> None:
    adapter = StubAdapter(responses=["I think the revenue was $400B."])
    extractor = _Extractor(adapter=adapter)
    with pytest.raises(ExtractionError, match="not valid JSON"):
        await extractor.run(raw=b"x", meta={})


async def test_json_array_response_raises_extraction_error() -> None:
    adapter = StubAdapter(responses=["[1, 2, 3]"])
    extractor = _Extractor(adapter=adapter)
    with pytest.raises(ExtractionError, match="must be a JSON object"):
        await extractor.run(raw=b"x", meta={})


# ---- Retry policy ---------------------------------------------------------


async def test_transient_then_success() -> None:
    good = make_response(
        sections={"document_summary": "ok"},
        json_artifacts={"metadata.json": {"ticker": "AAPL", "fiscal_year": 2024}},
    )
    adapter = StubAdapter(
        responses=[TransientAdapterError("rate limit"), good],
    )
    extractor = _Extractor(adapter=adapter)
    result = await extractor.run(raw=b"x", meta={})
    assert result.sections == {"document_summary": "ok"}
    assert len(adapter.calls) == 2
    # Token usage is from the successful call only (the failing one didn't
    # return usage).
    assert result.meta["tokens_in"] == 10


async def test_transient_retries_exhausted_raises_transient() -> None:
    adapter = StubAdapter(
        responses=[
            TransientAdapterError("rate limit 1"),
            TransientAdapterError("rate limit 2"),
            TransientAdapterError("rate limit 3"),
        ],
    )
    extractor = _Extractor(adapter=adapter)
    with pytest.raises(TransientError) as excinfo:
        await extractor.run(raw=b"x", meta={})
    assert "after 3 attempts" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, TransientAdapterError)
    assert len(adapter.calls) == 3  # max_retries=2 ⇒ 3 attempts


async def test_permanent_adapter_error_does_not_retry() -> None:
    adapter = StubAdapter(responses=[AdapterAuthError("bad key")])
    extractor = _Extractor(adapter=adapter)
    with pytest.raises(ExtractionError, match="adapter error"):
        await extractor.run(raw=b"x", meta={})
    assert len(adapter.calls) == 1


async def test_token_usage_accumulates_across_retries() -> None:
    good = make_response(
        sections={"document_summary": "ok"},
        json_artifacts={"metadata.json": {"ticker": "AAPL", "fiscal_year": 2024}},
    )

    # Two successful calls in one run shouldn't happen in real flows, but
    # `_add_usage` should still combine them. Use a custom subclass that
    # calls twice to prove the accumulation.
    class TwoCallExtractor(_Extractor):
        async def extract(self, raw: bytes, meta: dict[str, Any]) -> ExtractionResult:
            await self.call_model(prompt=self.PROMPT, input_text="first")
            parsed = await self.call_model(prompt=self.PROMPT, input_text="second")
            return ExtractionResult(
                sections=parsed["sections"],
                json_artifacts=parsed["json_artifacts"],
            )

    adapter = StubAdapter(responses=[good, good])
    extractor = TwoCallExtractor(adapter=adapter)
    result = await extractor.run(raw=b"x", meta={})
    assert result.meta["tokens_in"] == 20  # 10 + 10
    assert result.meta["tokens_out"] == 40  # 20 + 20


# ---- Schema validation ----------------------------------------------------


async def test_missing_required_section_raises_validation_error() -> None:
    bad = make_response(
        sections={"sections/business": "no summary here"},  # missing document_summary
        json_artifacts={"metadata.json": {"ticker": "AAPL", "fiscal_year": 2024}},
    )
    adapter = StubAdapter(responses=[bad])
    extractor = _Extractor(adapter=adapter)
    with pytest.raises(ValidationError) as excinfo:
        await extractor.run(raw=b"x", meta={})
    assert "document_summary" in str(excinfo.value)
    assert excinfo.value.payload is not None
    assert excinfo.value.payload["sections"] == {"sections/business": "no summary here"}


async def test_missing_required_json_field_raises_validation_error() -> None:
    bad = make_response(
        sections={"document_summary": "ok"},
        json_artifacts={"metadata.json": {"ticker": "AAPL"}},  # missing fiscal_year
    )
    adapter = StubAdapter(responses=[bad])
    extractor = _Extractor(adapter=adapter)
    with pytest.raises(ValidationError, match="fiscal_year"):
        await extractor.run(raw=b"x", meta={})


async def test_wrong_json_field_type_raises_validation_error() -> None:
    bad = make_response(
        sections={"document_summary": "ok"},
        json_artifacts={"metadata.json": {"ticker": "AAPL", "fiscal_year": "2024"}},
    )
    adapter = StubAdapter(responses=[bad])
    extractor = _Extractor(adapter=adapter)
    with pytest.raises(ValidationError, match="expected int"):
        await extractor.run(raw=b"x", meta={})


async def test_validation_does_not_retry() -> None:
    bad = make_response(
        sections={},  # missing required document_summary
        json_artifacts={"metadata.json": {"ticker": "AAPL", "fiscal_year": 2024}},
    )
    adapter = StubAdapter(responses=[bad, bad])
    extractor = _Extractor(adapter=adapter)
    with pytest.raises(ValidationError):
        await extractor.run(raw=b"x", meta={})
    assert len(adapter.calls) == 1


# ---- Idempotency keys -----------------------------------------------------


async def test_cache_key_stable_for_same_inputs() -> None:
    adapter = StubAdapter(responses=[])
    extractor = _Extractor(adapter=adapter)
    raw = b"identical bytes"
    assert extractor.cache_key(raw) == extractor.cache_key(raw)


async def test_cache_key_changes_with_source_bytes() -> None:
    adapter = StubAdapter(responses=[])
    extractor = _Extractor(adapter=adapter)
    assert extractor.cache_key(b"a") != extractor.cache_key(b"b")


async def test_cache_key_changes_when_prompt_changes() -> None:
    class OldPrompt(_Extractor):
        PROMPT = "old prompt v1"

    class NewPrompt(_Extractor):
        PROMPT = "new prompt v2"

    a = OldPrompt(adapter=StubAdapter(responses=[]))
    b = NewPrompt(adapter=StubAdapter(responses=[]))
    assert a.cache_key(b"x") != b.cache_key(b"x")


async def test_cache_key_includes_schema_version() -> None:
    class V1(_Extractor):
        schema = ArtifactSchema(
            entity_path="{x}",
            sections=[SectionSpec(name="document_summary", required=True)],
            version="1",
        )

    class V2(_Extractor):
        schema = ArtifactSchema(
            entity_path="{x}",
            sections=[SectionSpec(name="document_summary", required=True)],
            version="2",
        )

    a = V1(adapter=StubAdapter(responses=[]))
    b = V2(adapter=StubAdapter(responses=[]))
    assert a.cache_key(b"x") != b.cache_key(b"x")


# ---- Cost accounting ------------------------------------------------------


async def test_cost_zero_when_no_pricing() -> None:
    adapter = StubAdapter(
        responses=[
            make_response(
                sections={"document_summary": "ok"},
                json_artifacts={"metadata.json": {"ticker": "AAPL", "fiscal_year": 2024}},
            ),
        ],
        usage=TokenUsage(prompt=1_000_000, completion=500_000, total=1_500_000),
    )
    extractor = _Extractor(adapter=adapter)
    result = await extractor.run(raw=b"x", meta={})
    assert result.meta["cost_usd"] == 0.0


async def test_cost_uses_pricing_table_when_present() -> None:
    class Priced(_Extractor):
        pricing = {"stub:stub-model": {"input": 3.0, "output": 15.0}}

    adapter = StubAdapter(
        responses=[
            make_response(
                sections={"document_summary": "ok"},
                json_artifacts={"metadata.json": {"ticker": "AAPL", "fiscal_year": 2024}},
            ),
        ],
        usage=TokenUsage(prompt=1_000_000, completion=500_000, total=1_500_000),
    )
    extractor = Priced(adapter=adapter)
    result = await extractor.run(raw=b"x", meta={})
    # 1M * $3/M (input) + 0.5M * $15/M (output) = 3 + 7.5 = 10.5
    assert result.meta["cost_usd"] == pytest.approx(10.5)


# ---- Subclass meta passthrough --------------------------------------------


async def test_subclass_meta_is_preserved_alongside_provenance() -> None:
    class WithCustomMeta(_Extractor):
        async def extract(self, raw: bytes, meta: dict[str, Any]) -> ExtractionResult:
            parsed = await self.call_model(prompt=self.PROMPT, input_text=raw.decode())
            return ExtractionResult(
                sections=parsed["sections"],
                json_artifacts=parsed["json_artifacts"],
                meta={"custom_field": "abc", "model": "overridden"},
            )

    adapter = StubAdapter(
        responses=[
            make_response(
                sections={"document_summary": "ok"},
                json_artifacts={"metadata.json": {"ticker": "AAPL", "fiscal_year": 2024}},
            ),
        ],
    )
    extractor = WithCustomMeta(adapter=adapter)
    result = await extractor.run(raw=b"x", meta={})
    assert result.meta["custom_field"] == "abc"
    # Subclass field overrides provenance default.
    assert result.meta["model"] == "overridden"
    # Other provenance fields still present.
    assert "source_hash" in result.meta


# ---- preprocess_pdf import fallback ---------------------------------------


async def test_preprocess_pdf_raises_helpful_error_when_pymupdf_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Hide pymupdf if it happens to be installed.
    monkeypatch.setitem(sys.modules, "pymupdf", None)
    extractor = _Extractor(adapter=StubAdapter(responses=[]))
    with pytest.raises(ImportError, match="reigner\\[ingestion\\]"):
        await extractor.preprocess_pdf(b"%PDF-1.4 fake")


# ---- __init__ wiring ------------------------------------------------------


async def test_init_requires_model_or_adapter() -> None:
    class NoModel(_Extractor):
        model = ""

    with pytest.raises(ValueError, match="set `model`"):
        NoModel()
