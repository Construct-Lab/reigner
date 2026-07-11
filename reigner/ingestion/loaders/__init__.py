"""Loaders — read one source into ``(raw bytes, meta dict)``.

Each loader handles one shape of source; the pipeline does the routing.
"""

from reigner.ingestion.loaders.base import LoadedDocument, Loader
from reigner.ingestion.loaders.html import HtmlLoader
from reigner.ingestion.loaders.json_doc import JsonLoader
from reigner.ingestion.loaders.markdown import MdLoader
from reigner.ingestion.loaders.pdf import PdfLoader
from reigner.ingestion.loaders.url import UrlLoader

__all__ = [
    "HtmlLoader",
    "JsonLoader",
    "LoadedDocument",
    "Loader",
    "MdLoader",
    "PdfLoader",
    "UrlLoader",
]
