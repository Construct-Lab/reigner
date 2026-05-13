# {project_name}

A Reigner agent scaffolded with `reigner init --blank`.

## Layout

- `REIGNER.md` — instructions the agent reads at session start.
- `reigner.yaml` — model, settings, tool wiring.
- `schema.yaml` — declared shape of your compiled artifacts.
- `extractors/` — your `LLMExtractor` subclasses (domain code).
- `library/raw/` — drop source documents here.
- `library/artifacts/` — populated by `reigner ingest`.
- `search-index/` — BM25 sidecar (populated by ingestion).
- `eval/cases.yaml` — assertions for `reigner eval`.

## Next steps

```bash
cp .env.example .env        # add your API key
# 1. write a real REIGNER.md and schema.yaml
# 2. fill in extractors/my_extractor.py
# 3. drop source docs in library/raw/
uv run reigner ingest       # compile raw → artifacts
uv run reigner chat         # talk to your agent
```

See [Reigner SPEC](https://github.com/Construct-Lab/reigner) for the full contract.
