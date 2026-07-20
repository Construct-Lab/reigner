# Case study: SEC 10-K filings

Reigner's flagship example is a citation-faithful agent over real **SEC Form 10-K
annual reports** — the hero use case, where getting the number *and its citation*
right is the whole job. The complete, runnable project lives in the repo at
[`examples/sec_10k/`](https://github.com/Construct-Lab/reigner/tree/main/examples/sec_10k);
this page is the tour of what it demonstrates and why it's built the way it is.

10-Ks are a good showcase because they're demanding in the ways a toy corpus
isn't:

- **Large.** One filing is 1.5–10 MB of HTML — far past what a single model call
  can read whole.
- **Uniform.** Every 10-K has the same skeleton (Item 1 Business, Item 1A Risk
  Factors, Item 7 MD&A, Item 8 financial statements), so one schema fits the whole
  corpus — the assumption Reigner's artifact model is built for.
- **Numeric, and citations matter.** "R&D expense in fiscal 2024" must resolve to
  a real figure from a real filing, cited to the exact field — the precise thing
  Reigner's faithfulness guarantees exist for.

**Corpus:** 15 filings — Apple, Microsoft, Alphabet, Amazon, NVIDIA × fiscal years
2022–2024 — pulled from EDGAR. The filings are large and public, so they're **not
committed**; you build the corpus once with the bundled fetch script.

## Run it

The example was scaffolded with `reigner init --recipe document_qa` and then
customized (a real extractor, the SEC schema, the corpus builder, a 20-case eval).
From `examples/sec_10k/`:

```bash
cp .env.example .env          # add OPENAI_API_KEY
python fetch_filings.py       # download the 15 filings from EDGAR → library/raw/
uv run reigner ingest         # compile filings → library/artifacts/ + BM25 index
uv run reigner chat           # ask questions, get cited answers
```

`fetch_filings.py` needs **no API key** — EDGAR filings are public domain; the
script only asks for a descriptive `User-Agent` (edit the email at the top) and a
polite request rate. It resolves each filing through EDGAR's JSON endpoints
(ticker → CIK → submissions → primary document), so it's a reproducible,
self-documenting record of exactly which filings the corpus is.

## The compile step

Ingestion turns each raw filing into a uniform artifact the agent can query — the
agent never touches the raw HTML:

```text
library/raw/aapl-2024.htm
    │  HtmlLoader          reads bytes
    ▼
SecTenKExtractor          strips HTML (stdlib html.parser), slices to the
    │                     Business / Risk Factors / financial-review text,
    │                     one model call → sections + metadata.json
    ▼
library/artifacts/AAPL/2024/
    ├── document_summary
    ├── sections/{business,risk_factors,mdna}
    └── metadata.json      { revenue, net_income, rnd_expense, ... }
```

The **`metadata.json` artifact with named financial fields** is the linchpin.
Figures are stored as strings, verbatim ("391,035" stays exactly as printed), so a
number is citable as an exact field — `AAPL/2024/metadata.json#field=rnd_expense`
— rather than buried in prose. The schema requires only the fields every filing
has (`revenue`, `net_income`) and lets the rest be null when a company doesn't
break them out.

## Two extractor strategies

The example ships **both**, and the contrast is the interesting part:

| | Default: `SecTenKExtractor` | Alternative: `SecTenKMapReduce` |
|---|---|---|
| Model calls per filing | **one** | several (one per chunk + reduces) |
| How it bounds the input | code slices to Items 1 / 1A / 7 / 8 (`_sec_html.py`) | reads the whole doc in chunks |
| `metadata.json` figures | filled directly by the model | left null; agent cites them from `sections/mdna` |
| Best when | sections live in known places (10-Ks do) | big or unpredictable documents |

A 10-K's answers live in a few known places, so the **one-call** default is
cheapest and fills the figures directly — its cost is the HTML slicing in
`_sec_html.py`. When a corpus *doesn't* have that predictable structure, swap in
[`MapReduceExtractor`](usage.md#large--non-uniform-corpora): it reads the whole
document and lets the model find the sections, so you never write `extract()`. The
example's `extractors/mapreduce_extractor.py` is a runnable version — import
`SecTenKMapReduce` into `extractors/pipeline.py` to try it.

## Ask, and get a cited figure

```console
$ uv run reigner chat --print "What was Apple's research and development expense in fiscal 2024?"
Apple reported research and development expense of $31,370 million for fiscal 2024.

Sources
 [1] AAPL/2024/metadata.json#field=rnd_expense
```

The claim resolves through `get_json_field` to one field of one filing's compiled
`metadata.json` — the citation points at the exact source, not a page of prose.
Ask across filings ("compare R&D as a share of revenue for Apple, Microsoft, and
Nvidia across 2022–2024") and the agent reads each entity's `metadata.json` in
turn, citing each.

The config leans into faithfulness: a strong model at moderate reasoning effort, and the
`citation_strict`, `clarify_when_ambiguous`, and `targeted_retrieval` skills wired
in `reigner.yaml`.

## Prove it with eval

The faithfulness story is only worth its regression test. The suite is **20 cases
across six buckets** — single-fact numeric (7), cross-year trend (3), cross-entity
comparison (3), qualitative/section (3), ambiguity/entity-resolution (3), and one
out-of-corpus hallucination trap. Cases assert the *citation*, not the wording:

```yaml
# eval/cases.yaml
- id: aapl_fy2024_rnd
  query: "What was Apple's research and development expense in fiscal 2024?"
  expected_citations:
    - "AAPL/2024/metadata.json#field=rnd_expense"
  max_tokens: 20000
```

```bash
uv run reigner eval --profile read_only   # read_only so ambiguity cases can clarify
```

`coverage` confirms the expected artifact was actually retrieved; `faithfulness`
confirms every number in the answer traces to a registered citation (and flags any
that doesn't — including the hallucination-trap case). The example's acceptance
targets (SPEC section 21): ingest + chat on a clean checkout in under five minutes,
18+ of 20 cases correct with valid citations, and faithfulness flagging every
hallucinated number.

## What this exercises

| Reigner feature | Where it shows up here |
|---|---|
| Uniform artifact schema | one shape across 15 filings enables cross-company/-year comparison |
| Field-level citations | `get_json_field` → `metadata.json#field=…` |
| Extractor choice | one-call HTML slicing vs. `MapReduceExtractor` for the whole doc |
| On-demand skills | `citation_strict` / `clarify_when_ambiguous` / `targeted_retrieval` |
| Eval faithfulness / coverage | 20 cases asserting the citation, not the phrasing |

## Next steps

- **[`examples/sec_10k/`](https://github.com/Construct-Lab/reigner/tree/main/examples/sec_10k)**
  — the full runnable project and its README.
- **[Large or mixed corpora](usage.md#large--non-uniform-corpora)** — the
  `MapReduceExtractor` contract, for corpora without predictable structure.
- **[Evaluate your agent](usage.md#38-evaluate-your-agent--reigner-eval)** — every
  built-in check and the report format.
