"""Map-reduce extractor stub for a mixed (non-uniform) corpus.

Your documents are large and don't share a shape, so a single model call can
neither fit a whole document nor cover every section. `MapReduceExtractor` reads
each document in full: it MAPs the text in chunks (asking which sections each
chunk fills), then REDUCEs the per-section fragments to fit each section's
`max_chars`. You only supply the two prompts below — the base class owns
chunking, fan-out, reduction, and the final size guard, so `extract()` is
inherited (do not write it).

Fill in the three TODOs (model + both prompts), then wire this class into
`extractors/pipeline.py`. See SPEC.md §8.2 and the MapReduceExtractor docstring.
"""

from __future__ import annotations

from typing import Any

from reigner.artifacts import ArtifactSchema
from reigner.ingestion import MapReduceExtractor


class MyExtractor(MapReduceExtractor):
    schema = ArtifactSchema.from_yaml("schema.yaml")
    model = "..."  # TODO: e.g. "openai:gpt-5.5" or "anthropic:claude-sonnet-4-6"
    max_retries = 2

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
        # Feeds {filename} into MAP_PROMPT / REDUCE_PROMPT.
        return {"filename": meta.get("filename", "unknown")}

    async def summarize(self, sections: dict[str, str], meta: dict[str, Any]) -> dict[str, str]:
        # Synthesize the required summary from the already-reduced sections.
        compiled = "\n\n".join(f"## {name}\n{body}" for name, body in sections.items())
        response = await self.call_model(
            self.SUMMARY_PROMPT.format(filename=meta.get("filename", "unknown")),
            compiled[: self.reduce_input_chars],
        )
        return {"overview/topic_summary": str(response.get("summary", "")).strip()}
