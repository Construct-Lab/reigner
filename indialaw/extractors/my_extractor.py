"""Map-reduce extractor for the Indian-legal-foundations corpus.

The corpus documents are large (the Constitution is ~840K chars) and
heterogeneous, so a single model call can neither fit a whole document nor
cover every section. ``MapReduceExtractor`` owns the whole-document machinery —
page-aware chunking, the map fan-out, the per-section reduce, section-spec
rendering, and the ``max_chars`` guard. All that's left here is the
domain-specific part: the three prompts, the cross-section summary, and the
deterministic coverage computation.

* MAP    — each ``chunk_chars`` window is asked which topical sections it
           contributes to. Every page is seen; nothing is truncated.
* REDUCE — the base condenses each section's fragments to its ``max_chars``.
* SUMMARY — ``summarize`` synthesizes the required ``overview/topic_summary``
           (and a title) from the reduced sections.
* COVERAGE — ``post_process`` computes ``concept_coverage.json`` from which
           sections got filled — no model guesswork.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reigner.artifacts import ArtifactSchema
from reigner.ingestion import MapReduceExtractor

# All ingested PDFs sit under one conceptual module; the per-file slug is topic.
COURSE_MODULE = "indian_legal_system"


def derive_identifiers(filename: str) -> dict[str, str]:
    """Map a raw filename to the ``entity_path`` placeholders.

    ``schema.yaml`` declares ``entity_path: "{course_module}/{topic_id}"``, so
    the pipeline's ``identifiers_fn`` and this extractor must agree on these two
    keys. Keep this the single source of truth and import it in ``pipeline.py``.
    """
    stem = Path(filename).stem.lower()
    topic_id = "".join(c if c.isalnum() else "-" for c in stem).strip("-") or "unknown"
    return {"course_module": COURSE_MODULE, "topic_id": topic_id}


class MyExtractor(MapReduceExtractor):
    schema = ArtifactSchema.from_yaml("schema.yaml")
    model = "openai:gpt-5.5"
    max_retries = 2
    # map_cache_dir = Path("./.reigner/ingest-cache")
    # map_concurrency = 4   # ← map up to 4 chunks of one doc at once

    

    # Cap on the text sent to one map call (~25K tokens); the document is
    # processed in as many windows as it takes. reduce_input_chars guards the
    # joined fragments handed to one reduce call.
    chunk_chars = 100_000
    reduce_input_chars = 80_000

    # The overall summary is synthesized by summarize(), not the map — so the
    # map isn't asked to fill it per chunk.
    MAP_EXCLUDE = frozenset({"overview/topic_summary"})

    # Corpus-level facts the model can't read off a single document. Two docs
    # are currently ingested (the scanned Handbook is parked for OCR).
    SOURCE_COUNT = 2
    CITATION_STRICTNESS = "strict"

    # Which schema section maps to which concept_coverage boolean.
    COVERAGE_FLAGS = {
        "foundations/rule_of_law": "rule_of_law_covered",
        "constitution/fundamental_rights": "fundamental_rights_covered",
        "constitution/fundamental_duties": "fundamental_duties_covered",
        "constitution/directive_principles": "directive_principles_covered",
        "constitution/framework": "constitution_framework_covered",
        "judiciary/court_structure": "judiciary_structure_covered",
        "procedure/case_flow": "legal_procedure_covered",
    }

    MAP_PROMPT = """\
You are reading PART of a document from a corpus on the foundations of the
Indian legal system. The document is: {filename}

For the section names listed below, extract the content from THIS PART that
belongs in each — faithful to the text, no invention. Return a single JSON
object mapping section name -> extracted content. Include a section ONLY if
this part genuinely contains relevant material; omit the rest. If this part
contributes nothing, return {{}}.

Sections:
{section_spec}

Output ONLY the JSON object — no markdown, no commentary."""

    REDUCE_PROMPT = """\
You are assembling the "{section}" section of a study artifact. Below are
fragments extracted from different parts of one document. Merge them into ONE
coherent, non-repetitive section, faithful to the fragments and grounded only
in them. Keep it under {max_chars} characters.

Return a single JSON object: {{"content": "<the section text>"}}.
Output ONLY the JSON object — no markdown, no commentary."""

    SUMMARY_PROMPT = """\
Below are the compiled sections of a study artifact for the document
"{filename}". Write a faithful 4-8 sentence overview of what the document
covers, grounded only in these sections. Max 1800 characters.

Return a single JSON object: {{"topic_title": "<short title>", "summary":
"<the overview>"}}. Output ONLY the JSON object — no markdown, no commentary."""

    def prompt_context(self, meta: dict[str, Any]) -> dict[str, Any]:
        return {"filename": meta.get("filename", "unknown")}

    async def summarize(self, sections: dict[str, str], meta: dict[str, Any]) -> dict[str, str]:
        # overview/topic_summary is required — synthesize it from the reduced
        # sections, and stash the model's title for post_process to read.
        compiled = "\n\n".join(f"## {name}\n{body}" for name, body in sections.items())
        response = await self.call_model(
            self.SUMMARY_PROMPT.format(filename=meta.get("filename", "unknown")),
            compiled[: self.reduce_input_chars],
        )
        fallback = Path(meta.get("filename", "unknown")).stem.replace("-", " ").title()
        meta["topic_title"] = str(response.get("topic_title") or fallback)
        return {"overview/topic_summary": str(response.get("summary", ""))}

    def post_process(
        self, sections: dict[str, str], meta: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        filename = meta.get("filename", "unknown")
        ids = derive_identifiers(filename)
        flags: dict[str, Any] = {
            flag: bool(sections.get(section, "").strip())
            for section, flag in self.COVERAGE_FLAGS.items()
        }
        flags["coverage_score"] = round(sum(bool(v) for v in flags.values()) / len(flags), 3)
        return {
            "topic_metadata.json": {
                "course_module": ids["course_module"],
                "topic_id": ids["topic_id"],
                "topic_title": meta.get("topic_title", ""),
                "primary_source_document": filename,
                "source_count": self.SOURCE_COUNT,
                "citation_strictness": self.CITATION_STRICTNESS,
                "strict_citations_required": True,
            },
            "concept_coverage.json": flags,
        }
