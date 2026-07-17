"""Single-call extractor stub for the document_qa recipe.

Your corpus is *uniform* — every document shares a shape — so one model call per
document can compile the whole artifact. Subclass `LLMExtractor`, point `model`
at your ingestion model, and refine `PROMPT` to match your `schema.yaml`
(`document_summary`, `sections/*`, `insights/*`, `metadata.json`). The base
class owns adapter wiring, retries, schema validation, and idempotency.

Copied to `extractors/my_extractor.py` at init; wire it into
`extractors/pipeline.py`.

Outgrowing a single call? If your documents are large (a single call can't hold
one) or your corpus is mixed (documents don't share a shape), graduate to
`MapReduceExtractor` — it reads each document in chunks and reduces per section.
See the map-reduce extractor stub and its docstring for that contract.
"""

from __future__ import annotations

from typing import Any

from reigner.artifacts import ArtifactSchema
from reigner.ingestion import ExtractionResult, LLMExtractor


class MyExtractor(LLMExtractor):
    """One-call extractor over a uniform corpus; set the model and refine the prompt."""

    schema = ArtifactSchema.from_yaml("schema.yaml")
    model = "openai:gpt-5.5"  # TODO: your ingestion model, "provider:model_id"
    max_retries = 2

    PROMPT = """\
You are compiling a structured artifact from one document. Extract faithfully —
never invent a figure, quote, or fact the text does not contain.

Return a single JSON object with exactly these two keys:

  "sections": {
    "document_summary": "<a faithful 4-8 sentence overview>",
    "sections/<name>": "<one entry per real section, e.g. sections/business>",
    "insights/<name>": "<optional derived, cross-cutting notes>"
  },
  "json_artifacts": {
    "metadata.json": { "entity_id": "...", "version": "...", "title": "..." }
  }

Output ONLY the JSON object."""

    async def extract(self, raw: bytes, meta: dict[str, Any]) -> ExtractionResult:
        """Compile one document into sections + json artifacts in a single call."""
        text = await self.raw_to_text(raw)
        response = await self.call_model(self.PROMPT, text)
        return ExtractionResult(
            sections=response.get("sections", {}),
            json_artifacts=response.get("json_artifacts", {}),
        )
