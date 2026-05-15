"""Loaders — read one source into ``(raw bytes, meta dict)``.

See SPEC.md §8 ("The Ingestion System") and issue #15. Each loader
handles one shape of source; the pipeline (T-16) does the routing.
"""

from reigner.ingestion.loaders.base import LoadedDocument, Loader
from reigner.ingestion.loaders.json_doc import JsonLoader
from reigner.ingestion.loaders.markdown import MdLoader
from reigner.ingestion.loaders.pdf import PdfLoader
from reigner.ingestion.loaders.url import UrlLoader

__all__ = [
    "JsonLoader",
    "LoadedDocument",
    "Loader",
    "MdLoader",
    "PdfLoader",
    "UrlLoader",
]
