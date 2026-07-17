# Case study: SEC 10-K filings

A worked example on a corpus that stresses every part of Reigner: **annual 10-K
reports filed with the SEC.** They're a good showcase because they're demanding in
exactly the ways a toy corpus isn't:

- **Large.** A single 10-K runs 100–300 pages — far past what one model call can
  read, so extraction has to go through [`MapReduceExtractor`](usage.md#large--non-uniform-corpora).
- **Uniform.** Every 10-K has the same skeleton (Business, Risk Factors, MD&A,
  Financial Statements), so one schema fits the whole corpus — the assumption
  Reigner's artifact model is built for.
- **Numeric, and citations matter.** "R&D expenses in 2024" must resolve to a real
  figure from a real filing, cited to the exact field — the precise thing
  Reigner's faithfulness guarantees exist for.

The end state: ask *"What were Apple's R&D expenses in 2024?"* and get the number,
grounded in a citation you can click back to the filing.

This page assumes you've done the [Quickstart](quickstart.md) and read the
[large-corpus section](usage.md#large--non-uniform-corpora) of the usage guide.

## 1. Scaffold and install

Start from the `document_qa` recipe — 10-Ks are a uniform corpus, its home case —
then add the loaders. 10-Ks are served as **HTML** on EDGAR, so `HtmlLoader`
handles them with no PDF dependency:

```bash
reigner init sec-10k --recipe document_qa
cd sec-10k
uv add 'reigner[openai,ingestion]'
```

## 2. Fetch the corpus (a script, not committed files)

Filings are large and not ours to redistribute, so the project ships a **fetch
script**, not the documents — `library/raw/` stays empty in git (a `.gitkeep`
holds the directory). The script walks the public EDGAR API: ticker → CIK →
latest 10-K → primary document.

```python
# scripts/fetch_10k.py — download the latest 10-K for a few tickers into library/raw/
import json
import time
import urllib.request
from pathlib import Path

# EDGAR requires a descriptive User-Agent with contact info.
UA = {"User-Agent": "reigner-example youremail@example.com"}
TICKERS = ["AAPL", "MSFT", "NVDA"]
OUT = Path("library/raw")


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req) as r:
        return r.read()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # ticker → CIK, from SEC's published map
    cik_map = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
    by_ticker = {row["ticker"]: row["cik_str"] for row in cik_map.values()}

    for ticker in TICKERS:
        cik = f"{by_ticker[ticker]:010d}"
        subs = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
        recent = subs["filings"]["recent"]
        # first 10-K in the recent list
        i = recent["form"].index("10-K")
        accession = recent["accessionNumber"][i].replace("-", "")
        doc = recent["primaryDocument"][i]
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{doc}"
        dest = OUT / f"{ticker.lower()}-10k.html"
        dest.write_bytes(get(url))
        print(f"✓ {ticker} → {dest}")
        time.sleep(0.5)  # be polite to EDGAR


if __name__ == "__main__":
    main()
```

```console
$ uv run python scripts/fetch_10k.py
✓ AAPL → library/raw/aapl-10k.html
✓ MSFT → library/raw/msft-10k.html
✓ NVDA → library/raw/nvda-10k.html
```

Then gitignore the downloads so the corpus never lands in version control:

```gitignore
# .gitignore
library/raw/*.html
```

## 3. Shape the schema

A 10-K's structure is stable, so declare it once. The key move is a
**`metrics.json` artifact** with named numeric fields — that's what makes a
figure citable as `AAPL/2024/metrics.json#field=research_and_development` instead
of buried in prose:

```yaml
# schema.yaml
entity_path: "{entity_id}/{version}"      # e.g. AAPL/2024 — ticker / fiscal year

sections:
  - name: document_summary
    required: true
    max_chars: 2000
  - name: sections/business
    max_chars: 6000
  - name: sections/risk_factors
    max_chars: 8000
  - name: sections/mdna              # Management's Discussion & Analysis
    max_chars: 8000

json_artifacts:
  - name: metrics.json
    fields:
      entity_id: str
      fiscal_year: str
      revenue: str
      net_income: str
      research_and_development: str
```

The numeric fields are `str`, not `float`, on purpose: a 10-K reports "$31,370
million" or "31.4 billion", and you want to cite the figure *as filed* rather than
coerce it and lose the units. The faithfulness check maps the claim to the field;
it doesn't do arithmetic.

## 4. Map-reduce extraction

One 10-K won't fit a single call, so subclass `MapReduceExtractor` — it reads the
filing in `chunk_chars`-capped windows, extracts per section, then reduces. The
**deterministic-coverage** pattern earns its keep here: derive `metrics.json`
completeness from which fields actually filled, so a filing that omits a line item
is visible instead of hallucinated.

```python
# extractors/my_extractor.py
from typing import Any

from reigner.artifacts import ArtifactSchema
from reigner.ingestion import MapReduceExtractor


class MyExtractor(MapReduceExtractor):
    schema = ArtifactSchema.from_yaml("schema.yaml")
    model = "openai:gpt-5.5"
    chunk_chars = 100_000
    map_concurrency = 4          # a 10-K maps in ~6–9 windows; run them 4 at a time

    MAP_EXCLUDE = frozenset({"document_summary"})   # synthesized in summarize()

    MAP_PROMPT = (
        "Extract per-section content from THIS part of a 10-K. {section_spec} "
        "For metrics.json, pull only figures stated verbatim in this part — never "
        "infer or compute. Leave a field absent if it isn't here."
    )
    REDUCE_PROMPT = "Merge the fragments for {section}, keep under {max_chars}."
    SUMMARY_PROMPT = "Write a faithful overview grounded only in these sections."

    def prompt_context(self, meta: dict[str, Any]) -> dict[str, Any]:
        return {"filename": meta.get("filename", "unknown")}

    async def summarize(self, sections: dict[str, str], meta: dict[str, Any]) -> dict[str, str]:
        compiled = "\n\n".join(f"## {n}\n{b}" for n, b in sections.items())
        resp = await self.call_model(self.SUMMARY_PROMPT, compiled[: self.reduce_input_chars])
        return {"document_summary": str(resp.get("summary", "")).strip()}

    def post_process(self, sections: dict[str, str], meta: dict[str, Any]) -> dict[str, dict[str, Any]]:
        # coverage computed from what filled — can't be hallucinated
        filled = [n for n, body in sections.items() if body.strip()]
        return {"metrics.json": {"sections_filled": len(filled)}}
```

Name entities by ticker + fiscal year so citations read `AAPL/2024`. In
`extractors/pipeline.py`, that's the one line to own:

```python
def derive_identifiers(loaded) -> dict[str, str]:
    # aapl-10k.html → ("aapl", "2024"); parse the year from the filing in practice
    stem = loaded.meta["filename"].split("-")[0]
    return {"entity_id": stem.upper(), "version": "2024"}
```

And swap the loader for HTML in the pipeline's `loaders=[...]` — `HtmlLoader()` in
place of the default markdown loader.

## 5. Ingest — with the map cache on

10-Ks are expensive to extract, and you'll iterate on the reduce prompt. Turn on
the [chunk-level map cache](usage.md#caching-ingestion) so editing `REDUCE_PROMPT`
re-pays only the reduce calls, not the whole map:

```python
class MyExtractor(MapReduceExtractor):
    ...
    map_cache_dir = Path("./.reigner/ingest-cache")   # enables the cache
```

```console
$ reigner ingest
# representative output
✓ loaded 3 documents
✓ extracted 3 entities → library/artifacts/
✓ built BM25 index → search-index/documents.json
```

Add a fourth filing later and re-run: the document-level skip compiles only the
new one, the other three are untouched.

## 6. Ask, and get a cited figure

```console
$ reigner chat --print "What were Apple's R&D expenses in fiscal 2024?"
# representative output
Apple reported $31.4 billion in research and development expenses for fiscal
2024. [1]

[1] AAPL/2024/metrics.json#field=research_and_development
```

The answer resolves through `get_json_field` to a single field of a single
filing's compiled `metrics.json` — the citation points at the exact source, not a
page of prose. Ask across filings ("compare R&D as a share of revenue for Apple,
Microsoft, and Nvidia") and the agent reads each entity's `metrics.json` in turn,
citing each.

## 7. Prove it with eval

The faithfulness story is only worth as much as its regression test. Encode the
question as an eval case that asserts the *citation*, not just the wording:

```yaml
# eval/cases.yaml
cases:
  - id: apple_rnd_2024
    query: "What were Apple's R&D expenses in 2024?"
    expected_citations:
      - "AAPL/2024/metrics.json#field=research_and_development"
    forbidden_phrases: ["I think", "approximately"]
    max_tokens: 20000
```

```console
$ reigner eval --case apple_rnd_2024
# representative output
| Case | faithfulness | repeated_calls | coverage | latency_cost |
|---|---|---|---|---|
| apple_rnd_2024 | ✓ | ✓ | ✓ | ✓ (8.1k tok · 1.2s) |

1 case · 1 passed · 0 failed
```

`coverage` confirms the expected citation was actually retrieved; `faithfulness`
confirms the numeric claim maps to a registered citation. Together they turn "the
answer looked right" into "the answer is grounded, and CI will catch it if that
ever stops being true."

## What this exercises

| Reigner feature | Where it shows up here |
|---|---|
| `MapReduceExtractor` | reading a 100+ page filing that won't fit one call (§4) |
| `map_concurrency` | mapping ~9 windows per filing, 4 at a time (§4) |
| Map cache | cheap reduce-prompt iteration on an expensive corpus (§5) |
| Deterministic coverage | `metrics.json` completeness computed, not asked (§4) |
| Field-level citations | `get_json_field` → `metrics.json#field=…` (§6) |
| Eval faithfulness / coverage | asserting the citation, not the phrasing (§7) |

## Next steps

- **[Large or mixed corpora](usage.md#large--non-uniform-corpora)** — the full
  map-reduce contract and the uniform-vs-mixed decision.
- **[Caching ingestion](usage.md#caching-ingestion)** — how the two caches
  compose, and the reduce-side-code footgun.
- **[Evaluate your agent](usage.md#38-evaluate-your-agent--reigner-eval)** — every
  built-in check and the report format.
