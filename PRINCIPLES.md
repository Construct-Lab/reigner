# Reigner — Design Principles

This document captures the *why* behind Reigner's design. The spec tells you **what to build**; this tells you **why decisions were made the way they were**, so they don't get quietly undone during refactoring or when adding new features.

When the spec and these principles disagree, treat it as a bug and surface it. They should always agree.

---

## 1. Reigner is for question-answering over compiled knowledge, not for autonomous action

Reigner exists to make a specific shape of agent reliable: an agent that answers questions about a corpus the developer has prepared, with citations that trace back to source artifacts.

It is **not** a coding agent harness, a sandbox runtime, or a multi-agent orchestrator. Tools like Flue, Claude Code, Codex CLI, and Daytona already serve those needs well, and trying to compete with them dilutes the wedge.

Concrete consequence: every API decision should be evaluated against the question *"does this make retrieval-shaped agents more trustworthy?"* If the answer is no, it doesn't belong in v0 — even if it would be useful for some other shape of agent.

---

## 2. Build fresh, don't port

Reigner's tools, contracts, and abstractions are written from scratch against a generic retrieval problem — not ported from a domain-specific predecessor.

The reasoning: contracts written for one domain carry assumptions that don't survive contact with other domains. A grep tool tuned for one corpus may have made the wrong default for another. Re-deriving forces those assumptions into the open and lets each one be evaluated deliberately.

The discipline: when implementing a tool, draft it, test it against the reference corpus, *then* compare to prior art. The comparison is for catching missed lessons, not for sourcing the contract. The order matters — reading prior work before drafting anchors you to it; reading after lets you see clearly what's load-bearing vs accidental.

What this rules out: copy-pasting contracts from a prior system, or treating a predecessor's parameter defaults as authoritative.

What it preserves: the right to look at prior art after a draft exists and ask "what did they decide here, and was it right for the generic case?"

---

## 3. Bounded outputs are the discipline

Every tool result must be **bounded, paginated, and self-describing**.

- *Bounded*: results are capped to fit comfortably in a model's working memory. No tool returns "everything that matched."
- *Paginated*: when a result is incomplete, the response says so explicitly (`has_more: true`, `truncated: true`, `next_offset: 1234`).
- *Self-describing*: missing fields are reported (`missing_keys: [...]`), available fields are listed (`available_keys: [...]`), and a model can tell from the response alone whether it got everything it asked for.

This is the contract that makes the rest of the system work. Truncation, caching, parallel execution, citation tracing — all of these depend on tool outputs being legible to a finite-context model.

What this rules out: shipping tools that return arbitrary-size blobs, tools that silently drop data, tools whose return shape varies based on success vs failure, tools that signal absence by returning empty without context.

This applies to *every* tool in the default surface. A tool that can't promise these things doesn't ship in `tools.artifacts`. It can ship in `tools.fs` (the explicit "raw" tier), but with documented warnings.

---

## 4. Read-mostly by default; the corpus is compiled, not navigated

Agent tools in Reigner are read-mostly. Writes happen through ingestion contracts, not through agent-callable tools.

The model: ingestion takes raw documents and *compiles* them into structured artifacts. Agents query that compiled artifact graph. They don't navigate a filesystem with bash; they don't construct paths; they don't write new artifacts.

Why: agents that navigate filesystems have to discover structure at runtime. That's slow, error-prone, and produces unpredictable results. Agents that query a compiled artifact graph operate against a known schema and produce predictable, testable behavior.

Concrete consequence: the default tool surface (`tools.artifacts`) addresses content by `(entity, version, section)` rather than by path. Paths are an implementation detail of the artifact store. There is no agent-facing `write_file`. If a developer needs raw filesystem access, they opt into `tools.fs` explicitly, with awareness of the tradeoffs.

This is the philosophical line between Reigner and Flue. Both are useful; they solve different problems.

---

## 5. Citations are first-class, not bolted on

Every numeric or factual claim in an answer should trace back to a source artifact via a `citation` event in the protocol.

This isn't a nice-to-have. It's the trust mechanism that distinguishes a "plausible answer" from a "verifiable answer." Users should be able to inspect, challenge, and confirm any claim the agent makes.

Concrete consequences:

- The event protocol has a dedicated `CitationEvent` type from day one.
- Tools that return facts include enough provenance to register a citation (file path, locator, value).
- The eval suite includes a `faithfulness` check that fails if any numeric claim in the final answer lacks a registered citation.
- The default `REIGNER.md` includes a `citation_strict` skill that teaches the model to refuse making numeric claims without citations.

What this rules out: treating citations as a UI feature, retrofitting citation chains after the loop is built, allowing tools to return values without provenance.

---

## 6. One agent, plural sessions

Reigner is single-agent on purpose. There is no multi-agent orchestration in the core. There are no sub-agents, no router agents, no synthesis agents.

Why: across the agent ecosystem, multi-agent systems consistently struggle with handoff, context loss, and orchestration overhead. Single-agent systems with the right tools can search, inspect, retry, compare, and synthesize in one continuous loop, and they're easier to debug, evaluate, and trust.

This is contrarian to where much of the ecosystem is going, and that's exactly why it's defensible.

What this *does* support: plural sessions on a single agent. Sessions are durable, forkable, branchable. A developer iterating on their ROLE can fork a session at turn 5, replay the same query against three variants, and diff the results. That's where the flexibility lives — in session-level experimentation, not agent-level multiplication.

If a developer genuinely needs multiple agents for their problem, they wire them up themselves. Reigner doesn't ship the abstraction.

---

## 7. MCP is an export, not the entry point

Tools in Reigner are written as Python-native callables (`@tool`-decorated functions). They can be *exported* as an MCP server via `reigner serve --mcp`, but the front door is Python.

Why: MCP is winning as an interop protocol, but forcing developers to spin up MCP servers to try the library is a heavy first-step cost. Python-native tools work in-process for development; MCP works for cross-process and cross-tool interop.

Concrete consequence: the `@tool` decorator enforces constraints that make tools MCP-clean (no positional-only args, no `**kwargs`, JSON-serializable returns). Costs a little Python flexibility, gains real interop.

What this means in practice: a developer writes `@tool` once, gets a Python callable for use in their own harness, and gets an MCP server they can plug into Claude Desktop, Cursor, Cline, mcp-agent, or any other MCP consumer. That's a genuinely strong pitch — Reigner isn't just a way to *consume* MCP, it's a way to *author* well-shaped MCP tools.

---

## 8. Convention by default, override when needed

Reigner ships opinionated defaults: an artifact layout, truncation budgets, compaction thresholds, parallel-read execution, ten-match grep caps. These reflect what held up under real production queries.

Defaults are explicit and overridable, but the bar for *changing* a default is high — defaults get tuned by running real queries and watching what breaks, not by individual preference.

What this rules out: configuration for its own sake, optional parameters that exist because someone might want them, settings exposed in `reigner.yaml` that nobody knows how to tune.

The test for adding a configuration knob: *"if I shipped this without the knob, would a real user be blocked?"* If no, leave it hardcoded. The strongest libraries are opinionated; their value comes from telling you the right way to do things.

---

## 9. The loop is small on purpose

The agent loop is roughly 300 lines. It's deliberately legible — a developer should be able to read it end-to-end and understand exactly what their agent does on each iteration.

Why: agent debugging is mostly about understanding what happened. Opaque loops are the #1 source of "why is my agent doing this?" pain. A small, readable loop with explicit handling for each guardrail (G1–G11) lets developers reason about behavior rather than guess.

What this rules out: framework-style loops with hooks layered on hooks, reflection-based dispatch that obscures control flow, abstractions that hide what the model is actually being told.

The eleven guardrails in the loop are baked-in defaults a developer opts *out* of, not into. Each one solves a real failure mode that recurred in production. Removing one should require a real reason and a test demonstrating it's no longer needed.

---

## 10. The CLI is utility, not the product

Reigner is a library first. The CLI exists to scaffold projects, run evals, inspect harness state, and serve the agent — not as the primary surface developers interact with.

Why: libraries get embedded in other applications. CLIs get used standalone. A developer building a customer-support agent isn't going to expose `reigner chat` to their users; they're going to import `Harness`, customize it, and embed it in their own service.

Concrete consequences: every CLI command is a thin wrapper over the library API. `reigner ingest` calls the same `IngestionPipeline.run()` a developer would call from their own code. There are no CLI-only features.

What this rules out: TUI-as-primary-surface (Pi, OpenCode), CLI-only configuration that can't be expressed in code, slash commands that hide complexity from the library API.

---

## 11. Out of scope is a feature

The most important part of the spec is the list of things Reigner deliberately doesn't do. That list isn't a roadmap — it's a contract.

Why: every framework that tried to do everything ended up doing nothing well. Reigner's value comes from being sharp about its niche. Multi-agent orchestration, sandboxing, hosted services, vector stores, LLM extractors, frontends — these are all reasonable things to build, but not in Reigner.

When new feature requests come in, the question is not *"is this useful?"* (it usually is). The question is *"does this serve the question-answering-over-compiled-knowledge use case better than any alternative?"* If the answer is no, it goes in someone else's library.

---

## A short note on disagreement

These principles will sometimes feel restrictive. That's the point — they're load-bearing. If a principle seems wrong for a specific case, the right move is to surface the tension explicitly, not to silently override it. Either the principle has an exception worth documenting, or the case isn't a fit for Reigner. Both outcomes are fine; the unprincipled middle (working around the principle without acknowledging it) is what causes drift.