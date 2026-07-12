"""The ingestion pipeline `reigner ingest` runs.

`reigner ingest` looks up `extractors.pipeline:pipeline` here. Each .htm in
library/raw/ goes HtmlLoader -> SecTenKExtractor -> artifact + BM25 writers.
"""

import re
from pathlib import Path
from typing import Any

from reigner.artifacts import ArtifactSchema
from reigner.ingestion import IngestionPipeline
from reigner.ingestion.loaders import HtmlLoader
from reigner.ingestion.writers import ArtifactWriter, Bm25IndexWriter

from .my_extractor import SecTenKExtractor

_schema = ArtifactSchema.from_yaml("schema.yaml")

# fetch_filings.py names files "{ticker}-{fiscal_year}.htm", e.g. aapl-2024.htm.
_FILENAME = re.compile(r"^(?P<ticker>[a-z]+)-(?P<year>\d{4})$", re.IGNORECASE)


def identify_filing(path: Path) -> dict[str, Any]:
    """Parse ticker + fiscal year from a filename, e.g. aapl-2024.htm.

    Returned under "identifiers" so it does double duty: the pipeline places the
    artifact at AAPL/2024/ (its default identifiers_fn reads meta["identifiers"]),
    and any extractor can read the same values off meta. One parser, not two.
    """
    match = _FILENAME.match(path.stem)
    if match is None:
        raise ValueError(
            f"filename {path.stem!r} isn't '{{ticker}}-{{year}}'; "
            "rename it or change identify_filing()"
        )
    return {"identifiers": {"entity_id": match["ticker"].upper(), "version": match["year"]}}


pipeline = IngestionPipeline(
    # The loader tags each filing with its identifiers; the pipeline's default
    # identifiers_fn reads them, so no separate identifiers_fn is needed.
    loaders=[HtmlLoader(meta_extractor=identify_filing)],
    transforms=[SecTenKExtractor()],  # the extractor carries its own schema
    writers=[
        ArtifactWriter(root="library/artifacts", schema=_schema),
        Bm25IndexWriter(path="search-index/documents.json"),
    ],
    concurrency=4,
    on_error="skip",
)
