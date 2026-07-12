# SEC 10-K example

The flagship example for Reigner: a citation-faithful agent over real SEC Form
10-K annual reports. It's the hero use case — retrieval-shaped question
answering over a compiled corpus where getting the number *and its citation*
right is the whole job.

**Corpus:** 15 filings — Apple, Microsoft, Alphabet, Amazon, NVIDIA × fiscal
years 2022–2024 — downloaded from EDGAR into `library/raw/` by `fetch_filings.py`.
The filings are large and public, so they aren't committed; you build them once
with one command (below).

This directory was scaffolded with `reigner init --recipe document_qa` and then
customized: a real extractor, the SEC artifact schema, the corpus, and a 20-case
eval suite. You can reproduce the same shape for your own corpus the same way.

## Quickstart

```bash
cp .env.example .env          # add OPENAI_API_KEY
python fetch_filings.py       # download the 15 filings from EDGAR → library/raw/
uv run reigner ingest         # compile filings → library/artifacts/ + BM25 index
uv run reigner chat           # ask questions, get cited answers
```

Example session:

```
› What was Apple's research and development expense in fiscal 2024?

Apple reported research and development expense of $31,370 million for
fiscal 2024.

Sources
 [1] AAPL/2024/metadata.json#field=rnd_expense
```

## How it works

Ingestion compiles each raw filing into a uniform artifact the agent can query;
the agent never touches the raw HTML.

```
library/raw/aapl-2024.htm
    │  HtmlLoader            reads bytes (decoding is the extractor's job)
    ▼
SecTenKExtractor            strips HTML (stdlib html.parser), slices to the
    │                       Business / Risk Factors / financial-review text,
    │                       one model call → sections + metadata.json
    ▼
library/artifacts/AAPL/2024/
    ├── document_summary
    ├── sections/business
    ├── sections/risk_factors
    ├── sections/mdna
    └── metadata.json        { revenue, net_income, rnd_expense, ... }
search-index/documents.json  BM25 index for keyword retrieval
```

A 10-K is 1.5–10 MB of HTML — too large to hand to one model call whole. The
extractor (`extractors/my_extractor.py`) does the shaping: strip tags with the
standard library (no bs4/lxml), then assemble a bounded input from the three
parts questions actually target — Item 1 (Business), Item 1A (Risk Factors), and
the number-dense financial review (Item 7 MD&A + the Item 8 statements, located
by scanning for the densest window of income-statement labels). Financial
figures are copied verbatim so the faithfulness check can trace every number in
an answer back to its citation.

## Choosing an extractor

This example makes one model call per filing — cheap, fast, and a good fit
because a 10-K's answers live in a few known places (Items 1, 1A, 7, 8). The cost
is the slicing in `_sec_html.py`, which finds those parts in each filer's messy
HTML.

If you'd rather not write that, Reigner ships `MapReduceExtractor`: it reads the
whole document in chunks and lets the model find the sections, so you don't write
`extract()` at all. `extractors/mapreduce_extractor.py` is a runnable version —
import `SecTenKMapReduce` into `extractors/pipeline.py` to try it.

- **One call (default):** predictable sections, lowest cost, and it fills the
  `metadata.json` figures directly.
- **MapReduce:** big or unpredictable documents, at the cost of several model
  calls per filing. It's good at prose sections, but its `metadata.json` figures
  are filled in by code, not the model — so `mapreduce_extractor.py` leaves the
  dollar amounts null and lets the agent cite them from `sections/mdna` instead.

## Files

| Path | Role |
|---|---|
| `fetch_filings.py` | Reproducible EDGAR corpus builder (see below). |
| `extractors/my_extractor.py` | `SecTenKExtractor` — HTML → uniform artifact, one model call. |
| `extractors/mapreduce_extractor.py` | `SecTenKMapReduce` — the read-the-whole-thing alternative (not wired). |
| `extractors/_sec_html.py` | HTML stripping and slicing helpers (not Reigner-specific). |
| `extractors/pipeline.py` | Wires `HtmlLoader → extractor → artifact + BM25 writers`. |
| `schema.yaml` | The compiled-artifact shape (sections + `metadata.json` fields). |
| `reigner.yaml` | Model, tools, and eval configuration. |
| `REIGNER.md` | The agent's runtime instructions. |
| `eval/cases.yaml` | 20 eval cases. |
| `library/raw/*.htm` | The committed filing snapshot. |

## Building the corpus

`fetch_filings.py` downloads the 15 filings into `library/raw/` (about 48 MB).
It's the one prerequisite for `reigner ingest`:

```bash
python fetch_filings.py
```

The filings are public domain and need no API key — EDGAR only asks for a
descriptive `User-Agent` (edit the email at the top of the script) and a polite
request rate. The script resolves each filing from EDGAR's JSON endpoints
(ticker → CIK → submissions → primary document), so it's a reproducible,
self-documenting record of exactly which filings the corpus is. Re-running it is
idempotent — it overwrites `library/raw/` in place.

## Evaluation

```bash
uv run reigner eval --profile read_only
```

The suite has 20 cases across six buckets: single-fact numeric (7), cross-year
trend (3), cross-entity comparison (3), qualitative/section (3), ambiguity /
entity resolution (3), and one out-of-corpus hallucination trap. Run under the
`read_only` profile so the ambiguity cases can call `request_clarification` —
the default `eval` profile strips it.

The checks (configured in `reigner.yaml`):

- **faithfulness** — every number in an answer must trace to a registered
  citation. Deterministic; flags every hallucinated figure.
- **coverage** — the artifacts named in `expected_citations` were actually
  retrieved.
- **entity_resolution** — ambiguous queries are clarified, not guessed.
- **repeated_calls** — no wasteful duplicate tool calls.

## Acceptance targets (SPEC.md §21)

1. Ingest + chat on a clean checkout in under 5 minutes.
2. 18+ of 20 eval cases correct with valid citations.
3. Faithfulness flags every hallucinated number.
