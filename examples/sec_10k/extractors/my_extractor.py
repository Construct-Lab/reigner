"""Extractor for the SEC 10-K corpus.

An extractor is small: subclass LLMExtractor, set the model and schema, and write
extract(). It reads the raw bytes, makes one model call, and returns the result;
the framework checks it against schema.yaml and writes the artifact.

The HTML parsing lives in _sec_html.py. That part isn't Reigner-specific, so for
your own corpus you'd swap it for whatever your documents need.
"""

from __future__ import annotations

import json
from typing import Any

from reigner.artifacts import ArtifactSchema
from reigner.ingestion import ExtractionResult, LLMExtractor

from . import _sec_html as sec


class SecTenKExtractor(LLMExtractor):
    """Turns one 10-K into its sections plus a metadata.json of key financials."""

    schema = ArtifactSchema.from_yaml("schema.yaml")
    model = "openai:gpt-5.5"
    max_retries = 2

    # The field list is rendered from the schema so there's only one place to
    # update it. Everything the schema can't say (units, what maps to what) goes
    # in the prose above it.
    PROMPT = (
        "You are compiling a structured artifact from one SEC Form 10-K annual "
        "report. Extract faithfully; never invent a figure, quote, or fact that "
        "isn't in the text.\n\n"
        "The input has three labeled excerpts: BUSINESS (Item 1), RISK FACTORS "
        "(Item 1A), and FINANCIAL REVIEW (Item 7 MD&A plus the Item 8 "
        "statements).\n\n"
        "For metadata.json:\n"
        '- Copy figures exactly as printed, commas and all (e.g. "391,035"). '
        "They are in millions unless the filing says otherwise.\n"
        "- revenue is total net sales or total revenue; rnd_expense is research "
        "and development expense; diluted_eps is diluted earnings per share.\n"
        "- Use null when a field isn't stated.\n\n"
        "Return only a JSON object matching this schema:\n"
        + json.dumps(schema.to_json_schema(), indent=2)
    )

    async def extract(self, raw: bytes, meta: dict[str, Any]) -> ExtractionResult:
        """Compile one filing into its sections and metadata.json."""
        text = sec.strip_html(raw)
        input_text = (
            f"[BUSINESS — Item 1]\n{sec.business(text)}\n\n"
            f"[RISK FACTORS — Item 1A]\n{sec.risk_factors(text)}\n\n"
            "[FINANCIAL REVIEW — Item 7 MD&A + Item 8 statements]\n"
            f"{sec.financial_review(text)}"
        )
        response = await self.call_model(self.PROMPT, input_text)
        return ExtractionResult(
            sections=response.get("sections", {}),
            json_artifacts=response.get("json_artifacts", {}),
        )
