"""Alternative extractor: read the whole filing with map-reduce.

An alternative for when you'd rather not slice the document by hand (compare
my_extractor.py + _sec_html.py). MapReduceExtractor chunks the whole filing, prompts
the model to pull each section out of every chunk, then merges the fragments per
section. You don't write extract() — you fill in the prompts.

The catch shows why the default extractor makes one model call: map-reduce hands
you prose sections, not fields, and post_process() can't call the model. Pulling
a single year's figure out of a 10-K's multi-year tables deterministically isn't
reliable (you grab the wrong column as often as not), so this extractor fills
only the identity fields and leaves the dollar amounts for the agent to cite from
sections/mdna. If you need them structured, that's the job the single-call
extractor uses the model for.

Not wired into the pipeline. To try it, import this class in extractors/pipeline.py
instead of SecTenKExtractor. It makes several model calls per filing, not one.
"""

from __future__ import annotations

from typing import Any

from reigner.artifacts import ArtifactSchema
from reigner.ingestion import MapReduceExtractor

from . import _sec_html as sec

_COMPANY_NAMES = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "GOOGL": "Alphabet Inc.",
    "AMZN": "Amazon.com, Inc.",
    "NVDA": "NVIDIA Corporation",
}
_PAGE_CHARS = 6_000


class SecTenKMapReduce(MapReduceExtractor):
    """Reads the whole 10-K in chunks — no section-finding heuristics."""

    schema = ArtifactSchema.from_yaml("schema.yaml")
    model = "openai:gpt-5.5"

    # How much text goes into one map call, and how much joined fragment text
    # goes into one reduce call. A filing is processed in as many map windows as
    # it takes. Roughly 4 chars per token, so 100K chars is about 25K tokens.
    chunk_chars = 100_000
    reduce_input_chars = 80_000

    # Optional dials, off by default:
    # map_concurrency = 4                             # map N chunks of one filing at once
    # map_cache_dir = Path("./.reigner/ingest-cache")  # skip re-mapping unchanged chunks

    # document_summary is built in summarize(), so don't ask the map for it.
    MAP_EXCLUDE = frozenset({"document_summary"})

    MAP_PROMPT = (
        "You are reading one chunk of {filename}, an SEC Form 10-K. Pull out "
        "whichever of these sections appear in this chunk:\n{section_spec}\n\n"
        "Copy any financial figures exactly as printed. Return a JSON object "
        "mapping section name to the text you found, and omit sections that "
        "aren't in this chunk."
    )
    REDUCE_PROMPT = (
        "Merge these fragments of the '{section}' section of a 10-K into one "
        "faithful, non-repetitive version under {max_chars} characters. "
        'Return {{"content": "..."}}.'
    )
    SUMMARY_PROMPT = (
        "Below are the compiled sections of {filename}, an SEC 10-K. Write a "
        "faithful 4-8 sentence overview of the filing, grounded only in these "
        'sections. Return {{"summary": "..."}}.'
    )

    async def raw_to_text(self, raw: bytes) -> str:
        """Strip the HTML and paginate so the base class can chunk it.

        The base splits on form-feeds, so we hand it page-sized pieces and let it
        pack them into chunk_chars windows.
        """
        text = sec.strip_html(raw)
        pages = [text[i : i + _PAGE_CHARS] for i in range(0, len(text), _PAGE_CHARS)]
        return "\f".join(pages)

    def prompt_context(self, meta: dict[str, Any]) -> dict[str, Any]:
        """Give the prompts the filename so the model knows which filing it's on."""
        return {"filename": meta.get("filename", "unknown")}

    async def summarize(self, sections: dict[str, str], meta: dict[str, Any]) -> dict[str, str]:
        """Write document_summary from the reduced sections in one model call."""
        compiled = "\n\n".join(f"## {name}\n{body}" for name, body in sections.items())
        response = await self.call_model(
            self.SUMMARY_PROMPT.format(filename=meta.get("filename", "unknown")),
            compiled[: self.reduce_input_chars],
        )
        return {"document_summary": str(response.get("summary", ""))}

    def post_process(
        self, sections: dict[str, str], meta: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """Fill metadata.json's identity fields; leave the figures to sections/mdna.

        post_process runs deterministically (no model call), and reliably picking
        one year's number out of a multi-year table is what the model is for, so
        the dollar fields stay null here.
        """
        # The loader's meta_extractor (identify_filing in pipeline.py) already
        # parsed these off the filename, so we just read them.
        ids = meta.get("identifiers", {})
        ticker, year = ids.get("entity_id", "UNKNOWN"), ids.get("version", "0")
        return {
            "metadata.json": {
                "entity_id": ticker,
                "company_name": _COMPANY_NAMES.get(ticker, ticker),
                "fiscal_year": year,
                "form_type": "10-K",
                "currency": "USD",
                "units": "millions",
                "revenue": None,
                "net_income": None,
            }
        }
