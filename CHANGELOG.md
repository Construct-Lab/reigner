# Changelog

All notable changes to this project will be documented in this file.

## [0.11.0] - 2026-08-05

### Bug Fixes

- Report fatal errors in plain print mode ([#135](https://github.com/Construct-Lab/reigner/issues/135))

### Documentation

- Lead with the harness problem, not the agent shape ([#146](https://github.com/Construct-Lab/reigner/issues/146))

### Features

- Read session history over HTTP ([#147](https://github.com/Construct-Lab/reigner/issues/147))

### Miscellaneous Tasks

- Source release notes from CHANGELOG.md, not a regeneration ([#144](https://github.com/Construct-Lab/reigner/issues/144))
- Point the release script's next-steps at release-notes.sh ([#145](https://github.com/Construct-Lab/reigner/issues/145))

## [0.10.0] - 2026-07-20

### Changed

- **The oracle now runs at `high` effort by default.** `oracle:` gains an `effort:` key (`low`…`max`). Previously the oracle adapter was built without an effort argument at all, so every escalation ran at `medium` and did not inherit `model.effort` — a project running the main loop at `high` escalated *downward*. Projects with an existing `oracle:` block get a more capable but more expensive escalation on their next run; set `effort: medium` under `oracle:` to keep the previous behaviour.

### Documentation

- Surface the harness — oracle mode, context guardrails, and the why ([#139](https://github.com/Construct-Lab/reigner/issues/139))
- Add a 'when to reach for Reigner' positioning line ([#140](https://github.com/Construct-Lab/reigner/issues/140))
- Add a 'Custom tools' section to the usage guide ([#141](https://github.com/Construct-Lab/reigner/issues/141))

### Features

- Add an effort knob to the oracle block ([#142](https://github.com/Construct-Lab/reigner/issues/142))

### Miscellaneous Tasks

- Keep behavioural-change notes in the changelog across releases ([#143](https://github.com/Construct-Lab/reigner/issues/143))

## [0.9.0] - 2026-07-20

### Changed

- **Model tuning is now controlled by `effort` (`low`…`max`, default `medium`) instead of `temperature`.** Frontier models that previously ran at their provider-default effort (often `high`) now default to `medium`. `temperature` is kept but opt-in: it is sent only when explicitly set, and only to models that accept it (never on the reasoning/effort path). Update `reigner.yaml` files that set `temperature:` to use `effort:` — see the config reference in `docs/guide/usage.md`.

### Features

- Replace temperature knob with first-class effort control ([#136](https://github.com/Construct-Lab/reigner/issues/136)) ([#138](https://github.com/Construct-Lab/reigner/issues/138))

### Documentation

- Remove SPEC from docs site and trim internal planning from it ([#137](https://github.com/Construct-Lab/reigner/issues/137))

## [0.8.1] - 2026-07-17

### Bug Fixes

- Correct CLI help tagline to match product tagline

### Documentation

- Update RELEASING.md for public repo and first-release TestPyPI check

### Miscellaneous Tasks

- Release v0.8.1

## [0.8.0] - 2026-07-17

### Bug Fixes

- Dedup citations on (source, locator, value) ([#123](https://github.com/Construct-Lab/reigner/issues/123))

### Documentation

- Mark REIGNER.md loader and skills tasks complete (merged in #113)
- Add T-117 HtmlLoader in TASKS.md ([#118](https://github.com/Construct-Lab/reigner/issues/118))
- Add plain-language one-liner to README
- Clarify MetricsPlugin emits spans for real tool calls only ([#131](https://github.com/Construct-Lab/reigner/issues/131))
- MkDocs Material site + lean README for OSS release ([#76](https://github.com/Construct-Lab/reigner/issues/76)) ([#128](https://github.com/Construct-Lab/reigner/issues/128))
- Absolute asset URLs in README + drop stale session diff ref ([#133](https://github.com/Construct-Lab/reigner/issues/133))

### Features

- REIGNER.md loader + skill composition ([#113](https://github.com/Construct-Lab/reigner/issues/113))
- Add document_qa recipe scaffold ([#115](https://github.com/Construct-Lab/reigner/issues/115))
- Code_navigator recipe with multi-root FsTools ([#116](https://github.com/Construct-Lab/reigner/issues/116))
- HtmlLoader for HTML document ingestion ([#119](https://github.com/Construct-Lab/reigner/issues/119))
- SEC 10-K reference example ([#34](https://github.com/Construct-Lab/reigner/issues/34)) ([#120](https://github.com/Construct-Lab/reigner/issues/120))
- Chat startup banner, /help, and slash-command completion ([#125](https://github.com/Construct-Lab/reigner/issues/125))

### Miscellaneous Tasks

- Release v0.8.0

### Refactor

- Unify adapter builder helpers behind build_adapter ([#114](https://github.com/Construct-Lab/reigner/issues/114))

## [0.7.0] - 2026-07-06

### Bug Fixes

- Isolate per-run token accounting with a ContextVar ([#108](https://github.com/Construct-Lab/reigner/issues/108))

### Documentation

- Adopt Google-style docstrings and strip internal design-doc refs ([#104](https://github.com/Construct-Lab/reigner/issues/104)) ([#105](https://github.com/Construct-Lab/reigner/issues/105))

### Features

- Chunk-level map cache hook for MapReduceExtractor ([#106](https://github.com/Construct-Lab/reigner/issues/106))
- Bounded-parallel map fan-out for MapReduceExtractor ([#109](https://github.com/Construct-Lab/reigner/issues/109))
- Refresh chat REPL rendering with collapsed retrieval ([#111](https://github.com/Construct-Lab/reigner/issues/111))
- Per-run cost on the chat recap line ([#112](https://github.com/Construct-Lab/reigner/issues/112))

### Miscellaneous Tasks

- Ignore .env file
- Release v0.7.0

## [0.6.0] - 2026-06-26

### Features

- Eval suite + runner ([#28](https://github.com/Construct-Lab/reigner/issues/28))
- Eval checks + reigner eval CLI ([#101](https://github.com/Construct-Lab/reigner/issues/101))
- Reigner session CLI (list/show/tree/fork/replay/export/import) ([#102](https://github.com/Construct-Lab/reigner/issues/102))
- Mid-run REPL type-ahead and steering ([#48](https://github.com/Construct-Lab/reigner/issues/48)) ([#103](https://github.com/Construct-Lab/reigner/issues/103))

### Miscellaneous Tasks

- Release v0.6.0

## [0.5.0] - 2026-06-10

### Bug Fixes

- Add Bm25IndexWriter to default ingest scaffold
- Normalize tool schemas for OpenAI strict mode ([#81](https://github.com/Construct-Lab/reigner/issues/81))
- Skip OpenAI strict for tools with Any-typed args ([#81](https://github.com/Construct-Lab/reigner/issues/81))
- Close out request_clarification call with a tool Turn ([#83](https://github.com/Construct-Lab/reigner/issues/83))
- Mixed schema relaxes json_artifact fields so partial docs don't dead-letter

### Documentation

- Track .env loading + documentation site tasks (T-74/75/76)
- Add docs/USAGE.md end-to-end usage guide
- Add full reigner.yaml reference and plugin examples to USAGE.md
- File v1 multimodal ingestion follow-ups (#86, #87)
- Add large and non-uniform corpora section to USAGE

### Features

- Session fork, replay + tree (T-25)
- HTTP server transport (SSE)
- Auto-load project .env at CLI startup
- Implement reigner init --guided default mode
- Add MapReduceExtractor base class for whole-document extraction
- Loud truncation guard in LLMExtractor.call_model
- Add ArtifactSchema.generic_default() preset for non-uniform corpora
- Guided init asks corpus uniformity; mixed branch layers schema
- Add post_process stub to map-reduce template

### Miscellaneous Tasks

- Release v0.5.0

## [0.4.0] - 2026-05-25

### Bug Fixes

- Wire artifacts/search/fs into `reigner inspect tools` ([#58](https://github.com/Construct-Lab/reigner/issues/58))

### Features

- Session store ([#67](https://github.com/Construct-Lab/reigner/issues/67))
- Plugin system
- Bundled plugins (metrics, pii_redact)

### Miscellaneous Tasks

- Release v0.4.0

## [0.3.0] - 2026-05-22

### Bug Fixes

- Use annotated tags in release script and restructure RELEASING.md
- Auto-register pseudo-tools and register_citation in Harness.from_config ([#64](https://github.com/Construct-Lab/reigner/issues/64))

### Features

- FS tools — raw filesystem surface (FsTools)
- Provenance and citations (T-12) ([#63](https://github.com/Construct-Lab/reigner/issues/63))

### Miscellaneous Tasks

- Release v0.3.0

## [0.2.0] - 2026-05-21

### Documentation

- Add repository guidelines
- Add design principles
- Expand ingestion spec
- Add CLAUDE.md for Claude Code guidance
- Add TASKS.md with implementation breakdown and GitHub issue links

### Features

- Initial commit
- Initialize Python package + REIGNER.md / no-cascade design update ([#35](https://github.com/Construct-Lab/reigner/issues/35))
- Typed event protocol (T-02)
- AgentState
- Model adapters
- Agent loop + Harness/Session API
- @tool decorator + ToolRegistry
- Pseudo-tools ([#42](https://github.com/Construct-Lab/reigner/issues/42))
- Implement artifact system
- Guardrails G1-G11 for agent loop ([#43](https://github.com/Construct-Lab/reigner/issues/43))
- LLMExtractor base class ([#44](https://github.com/Construct-Lab/reigner/issues/44))
- Shared types + config schema  ([#45](https://github.com/Construct-Lab/reigner/issues/45))
- CLI skeleton + reigner init ([#47](https://github.com/Construct-Lab/reigner/issues/47))
- CLI chat REPL ([#49](https://github.com/Construct-Lab/reigner/issues/49))
- Document loaders (PdfLoader, MdLoader, JsonLoader, UrlLoader) ([#50](https://github.com/Construct-Lab/reigner/issues/50))
- IngestionPipeline + ingestion writers ([#51](https://github.com/Construct-Lab/reigner/issues/51))
- CLI ingest + inspect commands ([#20](https://github.com/Construct-Lab/reigner/issues/20))
- BM25 search tools
- Artifact tools + ArtifactStore ([#9](https://github.com/Construct-Lab/reigner/issues/9))
- Wire BM25 search into Harness; hoist RunnableToolAdapter

### Miscellaneous Tasks

- Add release tooling (cliff.toml, release.sh, RELEASING.md)
- Release v0.2.0

### Refactor

- Route Harness tools through ToolRegistry

<!-- generated by git-cliff -->
