"""`Bm25Index` — pure-Python BM25 over the JSON sidecar written by ingestion.

The sidecar is loaded once at construction. Three `@tool(readonly=True)`
closures are returned by ``tools()``: ``bm25_search`` scores against the
concatenated text, ``filtered_search`` returns id-sorted entries without
scoring, and ``section_search`` scores against one named section per entry.

Tokenization is intentionally simple: lowercase + ``\\w+`` Unicode word
splitting. No stemming, no stopwords. Tokens correspond directly to source
substrings so snippets and citations stay faithful.

Degenerate states (missing sidecar, empty list, corrupt JSON, entries
without a ``sections`` key) never raise — they return an empty hit list
with a ``note`` field so the model sees an actionable signal.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, ClassVar, Literal

from reigner.tools.base import tool
from reigner.tools.search.base import ToolCallable
from reigner.tools.search.filters import matches, parse_filters

_K1 = 1.5
_B = 0.75
_TOP_K_MAX = 20
_TOP_K_DEFAULT = 5
_SNIPPET_RADIUS = 120
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_MISSING_INDEX_NOTE = "index not built; run `reigner ingest`"


def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


def _empty_result(note: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "hits": [],
        "total_matches": 0,
        "has_more": False,
        "truncated": False,
    }
    if note is not None:
        out["note"] = note
    return out


def _clamp_top_k(top_k: int) -> int:
    if top_k <= 0:
        return _TOP_K_DEFAULT
    return min(top_k, _TOP_K_MAX)


def _snippet(text: str, query_tokens: list[str]) -> str:
    """~240-char window around the earliest matched token.

    Falls back to the first ~240 chars if no token matches (shouldn't happen
    for a real BM25 hit, but keeps the helper total).
    """
    if not text:
        return ""
    lower = text.lower()
    earliest = -1
    for tok in query_tokens:
        idx = lower.find(tok)
        if idx != -1 and (earliest == -1 or idx < earliest):
            earliest = idx
    if earliest == -1:
        cut = text[: _SNIPPET_RADIUS * 2].strip()
        return cut if len(text) <= _SNIPPET_RADIUS * 2 else cut + "…"
    start = max(0, earliest - _SNIPPET_RADIUS)
    end = min(len(text), earliest + _SNIPPET_RADIUS)
    while start > 0 and text[start - 1].isalnum():
        start -= 1
    while end < len(text) and text[end].isalnum():
        end += 1
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


class Bm25Index:
    """BM25 search over the JSON sidecar produced by `Bm25IndexWriter`.

    The constructor reads the file once and builds an inverted index keyed
    on the concatenated ``text`` field. Per-section text is held verbatim
    so ``section_search`` can build a smaller per-call index on demand.
    """

    __reigner_backend__: ClassVar[Literal["search"]] = "search"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._entries: list[dict[str, Any]] = self._load_entries()
        self._N = len(self._entries)
        self._doc_tokens: list[list[str]] = []
        self._tf: list[dict[str, int]] = []
        self._df: dict[str, int] = {}
        self._doc_len: list[int] = []
        self._avgdl: float = 0.0
        self._build()

    def _load_entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        return [e for e in data if isinstance(e, dict) and "id" in e]

    def _build(self) -> None:
        total_len = 0
        for entry in self._entries:
            tokens = _tokenize(entry.get("text", "") or "")
            self._doc_tokens.append(tokens)
            tf: dict[str, int] = {}
            for tok in tokens:
                tf[tok] = tf.get(tok, 0) + 1
            self._tf.append(tf)
            self._doc_len.append(len(tokens))
            total_len += len(tokens)
            for tok in tf:
                self._df[tok] = self._df.get(tok, 0) + 1
        self._avgdl = (total_len / self._N) if self._N else 0.0

    def _score_doc(self, query_tokens: list[str], doc_idx: int) -> float:
        if self._avgdl == 0.0:
            return 0.0
        dl = self._doc_len[doc_idx]
        tf = self._tf[doc_idx]
        score = 0.0
        for term in query_tokens:
            df = self._df.get(term, 0)
            if df == 0:
                continue
            term_freq = tf.get(term, 0)
            if term_freq == 0:
                continue
            idf = math.log(1 + (self._N - df + 0.5) / (df + 0.5))
            norm = term_freq * (_K1 + 1) / (term_freq + _K1 * (1 - _B + _B * dl / self._avgdl))
            score += idf * norm
        return score

    def _format_hit(
        self, entry: dict[str, Any], score: float, snippet_text: str, query_tokens: list[str]
    ) -> dict[str, Any]:
        return {
            "id": entry.get("id", ""),
            "score": round(score, 6),
            "identifiers": dict(entry.get("identifiers", {})),
            "source": entry.get("source", ""),
            "snippet": _snippet(snippet_text, query_tokens),
        }

    def _search_text(
        self, query: str, raw_filters: dict[str, Any] | None, top_k: int
    ) -> dict[str, Any]:
        if not self._entries:
            return _empty_result(note=_MISSING_INDEX_NOTE)
        filter_ = parse_filters(raw_filters)
        tokens = _tokenize(query)
        if not tokens:
            return _empty_result()
        scored: list[tuple[float, int]] = []
        for idx, entry in enumerate(self._entries):
            if filter_ and not matches(entry.get("identifiers", {}), filter_):
                continue
            score = self._score_doc(tokens, idx)
            if score > 0.0:
                scored.append((score, idx))
        scored.sort(key=lambda pair: (-pair[0], self._entries[pair[1]].get("id", "")))
        hits = [
            self._format_hit(
                self._entries[idx],
                score,
                self._entries[idx].get("text", "") or "",
                tokens,
            )
            for score, idx in scored[:top_k]
        ]
        return {
            "hits": hits,
            "total_matches": len(scored),
            "has_more": len(scored) > top_k,
            "truncated": False,
        }

    def _search_filtered(self, raw_filters: dict[str, Any], top_k: int) -> dict[str, Any]:
        if not self._entries:
            return _empty_result(note=_MISSING_INDEX_NOTE)
        filter_ = parse_filters(raw_filters)
        matched = [
            entry
            for entry in self._entries
            if not filter_ or matches(entry.get("identifiers", {}), filter_)
        ]
        matched.sort(key=lambda e: e.get("id", ""))
        hits = [
            {
                "id": entry.get("id", ""),
                "score": 0.0,
                "identifiers": dict(entry.get("identifiers", {})),
                "source": entry.get("source", ""),
                "snippet": _snippet(entry.get("text", "") or "", []),
            }
            for entry in matched[:top_k]
        ]
        return {
            "hits": hits,
            "total_matches": len(matched),
            "has_more": len(matched) > top_k,
            "truncated": False,
        }

    def _search_section(self, query: str, section_name: str, top_k: int) -> dict[str, Any]:
        if not self._entries:
            return _empty_result(note=_MISSING_INDEX_NOTE)
        tokens = _tokenize(query)
        if not tokens:
            return _empty_result()
        section_docs: list[tuple[dict[str, Any], str, list[str], dict[str, int]]] = []
        df: dict[str, int] = {}
        total_len = 0
        for entry in self._entries:
            sections = entry.get("sections")
            if not isinstance(sections, dict):
                continue
            text = sections.get(section_name)
            if not isinstance(text, str) or not text:
                continue
            sec_tokens = _tokenize(text)
            tf: dict[str, int] = {}
            for tok in sec_tokens:
                tf[tok] = tf.get(tok, 0) + 1
            for tok in tf:
                df[tok] = df.get(tok, 0) + 1
            total_len += len(sec_tokens)
            section_docs.append((entry, text, sec_tokens, tf))
        if not section_docs:
            return _empty_result(
                note=(
                    f"no entries have a section named {section_name!r} "
                    "(sidecar may predate section indexing — re-run `reigner ingest`)"
                )
            )
        n = len(section_docs)
        avgdl = total_len / n if n else 0.0
        scored: list[tuple[float, int]] = []
        for idx, (_entry, _text, sec_tokens, tf) in enumerate(section_docs):
            if avgdl == 0.0:
                continue
            dl = len(sec_tokens)
            score = 0.0
            for term in tokens:
                term_df = df.get(term, 0)
                if term_df == 0:
                    continue
                term_freq = tf.get(term, 0)
                if term_freq == 0:
                    continue
                idf = math.log(1 + (n - term_df + 0.5) / (term_df + 0.5))
                norm = term_freq * (_K1 + 1) / (term_freq + _K1 * (1 - _B + _B * dl / avgdl))
                score += idf * norm
            if score > 0.0:
                scored.append((score, idx))
        scored.sort(key=lambda pair: (-pair[0], section_docs[pair[1]][0].get("id", "")))
        hits = [
            self._format_hit(
                section_docs[idx][0],
                score,
                section_docs[idx][1],
                tokens,
            )
            for score, idx in scored[:top_k]
        ]
        return {
            "hits": hits,
            "total_matches": len(scored),
            "has_more": len(scored) > top_k,
            "truncated": False,
        }

    def tools(self) -> list[ToolCallable]:
        index = self

        @tool(readonly=True, cache=True)
        async def bm25_search(
            query: str,
            filters: dict[str, str | list[str]] | None = None,
            top_k: int = _TOP_K_DEFAULT,
        ) -> dict[str, Any]:
            """BM25 search across all compiled documents.

            Returns up to ``top_k`` hits (capped at 20) sorted by relevance,
            each with id, score, identifiers, source, and a short snippet.
            ``filters`` restricts results by exact-match against identifier
            keys (scalar or list-as-OR). Empty query raises ValueError.
            """
            if not query.strip():
                raise ValueError("query must be non-empty")
            return index._search_text(query, filters, _clamp_top_k(top_k))

        @tool(readonly=True, cache=True)
        async def filtered_search(
            filters: dict[str, str | list[str]],
            top_k: int = _TOP_K_DEFAULT,
        ) -> dict[str, Any]:
            """Return entries matching ``filters``, sorted by id ascending.

            No scoring; use this to enumerate documents by identifier when
            you already know what you're looking for. Capped at top_k=20.
            """
            return index._search_filtered(filters, _clamp_top_k(top_k))

        @tool(readonly=True, cache=True)
        async def section_search(
            query: str,
            section_name: str,
            top_k: int = _TOP_K_DEFAULT,
        ) -> dict[str, Any]:
            """BM25 search scoped to one named section across documents.

            Builds a per-call section index and scores ``query`` against the
            text of the named section only. Useful when the agent knows the
            schema and wants to constrain retrieval to e.g. risk_factors.
            """
            if not query.strip():
                raise ValueError("query must be non-empty")
            return index._search_section(query, section_name, _clamp_top_k(top_k))

        return [bm25_search, filtered_search, section_search]


__all__ = ["Bm25Index"]
