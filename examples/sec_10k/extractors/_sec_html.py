"""Text prep for 10-K filings.

Not Reigner-specific. A 10-K is a big, messy HTML file (1.5-10 MB) and even the
stripped text is too long for one model call, so these helpers strip the markup
and pull out the three parts we actually ask about. Swap this out for whatever
your own corpus needs; my_extractor.py stays the same either way.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

# Income-statement / MD&A words. Whichever window of text has the most of these
# is the part with the numbers, wherever a given company put it.
_FINANCIAL_LABELS = re.compile(
    r"net income|net sales|total revenue|cost of (?:sales|revenue)|gross margin|"
    r"research and development|operating income|total assets|"
    r"cash and cash equivalents|diluted|provision for income taxes",
    re.IGNORECASE,
)
_BUSINESS = re.compile(r"^\s*item\s+1\b(?!\s*a)", re.IGNORECASE | re.MULTILINE)
_RISK = re.compile(r"^\s*item\s+1a\b|risk factors", re.IGNORECASE | re.MULTILINE)
_SKIP_TAGS = {"script", "style", "head"}
_BREAK_TAGS = {"p", "div", "tr", "br", "li", "h1", "h2", "h3", "table", "td"}


class _TextExtractor(HTMLParser):
    """Collects visible text, adding a newline at each block boundary."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if tag in _BREAK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def strip_html(raw: bytes) -> str:
    """Drop the tags and tidy the whitespace, leaving plain text."""
    parser = _TextExtractor()
    parser.feed(raw.decode("utf-8", "replace"))
    text = html.unescape(parser.text())
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n[ \t]*", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def _slice_at_densest(text: str, pattern: re.Pattern[str], length: int) -> str:
    """Slice ``length`` chars from the busiest match of ``pattern``.

    A heading like "Risk Factors" shows up twice: once in the table of contents
    (mostly dots and page numbers) and once at the real section (prose). The real
    one has more letters right after it, so pick that.
    """
    best_start: int | None = None
    best_density = -1
    for match in pattern.finditer(text):
        window = text[match.start() : match.start() + 1500]
        density = sum(char.isalpha() for char in window)
        if density > best_density:
            best_density = density
            best_start = match.start()
    return text[best_start : best_start + length] if best_start is not None else ""


def business(text: str) -> str:
    """Item 1 — what the company does."""
    return _slice_at_densest(text, _BUSINESS, 12_000)


def risk_factors(text: str) -> str:
    """Item 1A — the principal risks."""
    return _slice_at_densest(text, _RISK, 12_000)


def financial_review(text: str, size: int = 120_000, step: int = 4_000) -> str:
    """Item 7 MD&A plus the Item 8 statements — the part with the numbers.

    Slides a window over the text and returns the position with the most
    financial words, so it works regardless of where a filer put them.
    """
    best_start = 0
    best_score = -1
    for start in range(0, max(1, len(text) - size + 1), step):
        score = len(_FINANCIAL_LABELS.findall(text, start, start + size))
        if score > best_score:
            best_score = score
            best_start = start
    return text[best_start : best_start + size]
