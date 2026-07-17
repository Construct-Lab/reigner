# Quickstart

From install to a cited answer in about five minutes, using the `document_qa`
recipe — a ready-to-run project you point at your own documents. It ships a
filled-in schema, extractor, and pipeline, so there's no code to write for a first
answer. For the full command surface and customization, see the
[usage guide](usage.md).

## 1. Install

```bash
uv add 'reigner[openai,ingestion]'
```

`openai` pulls the SDK for the recipe's default ingestion model; `ingestion` pulls
the document loaders. Prefer Claude or Gemini? Swap the extra (`anthropic` /
`gemini`) and change the model line in step 4.

## 2. Scaffold a project

```console
$ reigner init myqa --recipe document_qa
✓ Scaffolded myqa/ (document_qa recipe mode)
$ cd myqa
```

## 3. Add your API key

```bash
cp .env.example .env
# edit .env → OPENAI_API_KEY=sk-...
```

Reigner auto-loads this `.env` from the project root — no `export` needed.

## 4. Drop in a corpus

Put a document or two in `library/raw/`. For a throwaway first run, one tiny
markdown file is enough:

```markdown
<!-- library/raw/faq.md -->
# Orbit FAQ

## Pricing
Orbit is $8 per user per month, billed annually.
```

The recipe's default ingestion model is `openai:gpt-5.5`. To use another provider,
edit the `model` line in `extractors/my_extractor.py`.

## 5. Compile the corpus

```console
$ reigner ingest
# representative output
✓ loaded 1 document
✓ extracted 1 entity → library/artifacts/
✓ built BM25 index → search-index/documents.json
```

Want to see the plan first without spending tokens? `reigner ingest --dry-run`
lists the file → loader mapping and exits.

## 6. Ask a question

```console
$ reigner chat
› What does Orbit cost?
# representative output
  ✓ Retrieved  2 calls · 6.1k tok · $0.004 · 1.8s

  Sources
    [1] faq.md  section=pricing

  ╭─ Answer ──────────────────────────────╮
  │  Orbit is $8 per user per month. [1]   │
  ╰────────────────────────────────────────╯
```

The answer is grounded in a retrieved source and cited inline as `[1]`. Swap in
your own documents and re-run `ingest` — new files compile, unchanged ones are
skipped.

## Where to go next

- **[Usage guide](usage.md)** — every command and flag, plus the full
  configuration reference.
- **[Large or mixed corpora](usage.md#large--non-uniform-corpora)** — map-reduce
  extraction for big PDFs and documents that don't share a shape.
- **[The `code_navigator` recipe](usage.md#312-the-code_navigator-recipe-multi-repo)**
  — one agent reading across several repositories, with no ingestion step.
- **[Observability](observability.md)** — export the agent loop as OpenTelemetry
  spans.
