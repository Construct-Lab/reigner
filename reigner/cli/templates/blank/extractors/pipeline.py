"""Ingestion pipeline — wired by ``reigner ingest``.

Bare ``reigner ingest`` resolves ``extractors.pipeline:pipeline`` against
the project root, so the top-level ``pipeline`` symbol below is the
landing pad. Uncomment, adapt loaders/writers to your schema, and run.

See SPEC.md §8 for the full ingestion contract.
"""

# from reigner.artifacts import ArtifactSchema
# from reigner.ingestion import IngestionPipeline
# from reigner.ingestion.loaders import JsonLoader, MdLoader, PdfLoader
# from reigner.ingestion.writers import ArtifactWriter, Bm25IndexWriter
#
# from .my_extractor import MyExtractor
#
# _schema = ArtifactSchema.from_yaml("schema.yaml")
#
# pipeline = IngestionPipeline(
#     loaders=[PdfLoader(), MdLoader(), JsonLoader()],
#     transforms=[MyExtractor(schema=_schema)],
#     writers=[
#         ArtifactWriter(root="library/artifacts", schema=_schema),
#         Bm25IndexWriter(path="search-index/documents.json"),
#     ],
#     concurrency=4,
#     on_error="skip",
# )
