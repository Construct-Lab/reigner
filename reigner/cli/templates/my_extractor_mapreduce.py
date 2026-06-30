"""Map-reduce extractor stub for a mixed (non-uniform) corpus.

Your documents are large and don't share a shape, so a single model call can
neither fit a whole document nor cover every section. `MapReduceExtractor` reads
each document in full: it MAPs the text in chunks (asking which sections each
chunk fills), then REDUCEs the per-section fragments to fit each section's
`max_chars`. You only supply the two prompts below — the base class owns
chunking, fan-out, reduction, and the final size guard, so `extract()` is
inherited (do not write it).

Fill in the three TODOs (model + both prompts), then wire this class into
`extractors/pipeline.py`. See the MapReduceExtractor docstring for the contract.

Need deterministic JSON artifacts (metadata, coverage flags computed from which
sections filled — never asked of the model)? Override `post_process(sections,
meta)` to return them. Guided mixed schemas relax JSON fields to optional, so a
partial document never dead-letters; `post_process` is how you populate them.
"""

from __future__ import annotations

from pathlib import Path  # noqa: F401  (used by the map_cache_dir opt-in below)
from typing import Any

from reigner.artifacts import ArtifactSchema
from reigner.ingestion import MapReduceExtractor


class MyExtractor(MapReduceExtractor):
    """Map-reduce extractor for a mixed corpus; fill in the model and prompts."""

    schema = ArtifactSchema.from_yaml("schema.yaml")
    model = "..."  # TODO: e.g. "openai:gpt-5.5" or "anthropic:claude-sonnet-4-6"
    max_retries = 2

    # Uncomment to cache each chunk's map call to disk. A re-run with an
    # unchanged map prompt then makes zero map model calls (editing only the
    # REDUCE_PROMPT still re-runs reduce, but every map call is a cache hit).
    # map_cache_dir = Path("./.reigner/ingest-cache")

    # overview/topic_summary is the one required section; it's synthesized from
    # the reduced sections by summarize() below, so don't ask the map for it.
    MAP_EXCLUDE = frozenset({"overview/topic_summary"})

    MAP_PROMPT = """\
You are reading PART of the document "{filename}".

For the section names below, extract the content from THIS PART that belongs in
each — faithful to the text, no invention. Return a single JSON object mapping
section name -> extracted content. Include a section ONLY if this part has
relevant material; if it has none, return {{}}.

Sections:
{section_spec}

Output ONLY the JSON object."""

    REDUCE_PROMPT = """\
You are assembling the "{section}" section for "{filename}". Below are fragments
extracted from different parts of the document. Merge them into ONE coherent,
non-repetitive section, grounded only in the fragments. Keep it under
{max_chars} characters.

Return a single JSON object: {{"content": "<the section text>"}}.
Output ONLY the JSON object."""

    SUMMARY_PROMPT = """\
Below are the compiled sections of an artifact for "{filename}". Write a
faithful 4-8 sentence overview grounded only in these sections.

Return a single JSON object: {{"summary": "<the overview>"}}.
Output ONLY the JSON object."""

    def prompt_context(self, meta: dict[str, Any]) -> dict[str, Any]:
        """Provide ``{filename}`` (and friends) to the map/reduce prompts."""
        return {"filename": meta.get("filename", "unknown")}

    async def summarize(self, sections: dict[str, str], meta: dict[str, Any]) -> dict[str, str]:
        """Synthesize the required summary section from the reduced sections."""
        compiled = "\n\n".join(f"## {name}\n{body}" for name, body in sections.items())
        response = await self.call_model(
            self.SUMMARY_PROMPT.format(filename=meta.get("filename", "unknown")),
            compiled[: self.reduce_input_chars],
        )
        return {"overview/topic_summary": str(response.get("summary", "")).strip()}

    def post_process(
        self, sections: dict[str, str], meta: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """Compute deterministic JSON artifacts from the filled sections."""
        # Deterministic JSON artifacts — computed from which sections actually
        # filled, never asked of the model. Can't hallucinate, can't dead-letter.
        # Adapt the keys below to the json_artifacts your schema.yaml declares.
        filled = [name for name, body in sections.items() if body.strip()]
        coverage_score = round(len(filled) / max(len(self.schema.sections), 1), 3)
        return {
            "metadata.json": {
                "source_document": meta.get("filename", "unknown"),
                "sections_filled": len(filled),
                "coverage_score": coverage_score,
                # TODO: add the fields your json_artifacts declare, e.g. a
                # per-concept boolean: "rights_covered": bool(sections.get(...)).
            },
        }
