# Architecture: the harness

Reigner's core is not a wrapper around a model call. It is a small, deliberately
legible agent loop with explicit **context-management guardrails** — the part of
the system that keeps a single agent efficient and cheap as its context grows.

Everything on this page lives under `reigner/harness/`. The design rule: the loop
stays readable end to end. No abstraction hides control flow; every special case
is visible in one file.

## The loop

The whole thing is one `async def run_loop(state) -> AsyncIterator[Event]`
(`reigner/harness/loop.py`). Each yield is a checkpoint the caller can stop at —
cancelling the iterator cancels the loop. There are no background tasks and no
speculative work:

> **one iteration is one model call**, visible to the caller through the event stream.

That constraint is what makes the loop auditable. If you want to know what the
agent did, you read the events in order — there is no hidden second track.

## Oracle mode: pay frontier prices only when it's worth it

The most distinctive lever in the harness. A **cheap default model** runs the loop.
When a question genuinely needs deeper reasoning than retrieval has produced, the
model calls the `escalate_to_oracle` pseudo-tool. The loop intercepts it, swaps in
a **stronger oracle adapter for exactly one turn**, then reverts automatically.

```
turn 1   default model   → retrieve, retrieve
turn 2   default model   → "still stuck" → escalate_to_oracle(reason=…)
turn 3   ORACLE model    → deeper reasoning over what was gathered   ← single turn
turn 4   default model   → format the cited answer
```

The escalation is deliberately **hard to abuse**. The pseudo-tool's own contract
tells the model: use this only after two or three iterations of genuine stall,
never as a default, and never before retrieval is exhausted. The `reason` is
logged and surfaced in eval, so cheap-model laziness shows up in the numbers.

The mechanism is tiny (`reigner/harness/oracle.py`): `arm()` marks the next
iteration oracle-served; `pick_adapter()` returns the oracle adapter once, clearing
the flag so the following turn reverts. Configure it by setting an oracle model in
`reigner.yaml`; if the model escalates with no oracle configured, that surfaces as
a clear error rather than silently falling back.

**Why it matters:** most turns in a retrieval agent are routine — search the store,
format an answer. You should not pay a frontier model's price for those. Oracle mode
lets a small model drive and spends the expensive model only on the turns that
actually need it.

## Context stays bounded under pressure

The loop wires eleven numbered guardrails (G1–G11), each in its own module. They
exist so long runs don't blow the context budget or the bill.

| Guardrail | Module | What it does |
|---|---|---|
| **G1** — stable/dynamic prompt boundary | `state.build_prompt` | Separates the stable system prompt from per-turn dynamic context so caching works. |
| **G2** — per-tool truncation | `truncation.py` | Bounds every tool result against a char budget on its JSON form, respecting JSON boundaries. |
| **G3** — iteration nudge | `nudges.py` | Periodically reminds the model of the goal and remaining budget. |
| **G4** — consecutive-error nudge | `nudges.py` | After N tool errors in a row, injects an early-stop nudge before the loop hard-aborts. |
| **G5 / G10** — progressive compaction | `compaction.py` | Tiered history summarization driven by context pressure (see below). |
| **G6 / G7** — dynamic context refresh | `state.refresh_context` | Refreshes per-turn variables (`iters_remaining`, `now`, `answer_id`). |
| **G8** — scratchpad | `save_note` | A notes channel that **survives compaction** — the explicit way to carry facts across a long run. |
| **G9** — tool-result cache | `cache.py` | A per-session cache consulted before any tool executes. |
| **G11** — parallel reads | `parallel.py` | When every real call in a turn is read-only, they run concurrently. |

### Progressive compaction (G5 / G10)

When `context_pressure()` crosses configurable thresholds, the loop compacts history
in tiers and emits a `CompactionEvent` so UIs can show what happened:

| Tier | Pressure | Action |
|---|---|---|
| 1 | ≥ 80% | Keep the last *N* turns verbatim; collapse older turns into one synthetic summary turn. |
| 2 | ≥ 90% | Also shrink retained tool results to a one-line description each, keeping the history's shape. |
| 3 | ≥ 95% | Drop history to the last turn plus the summary. |

Across every tier, the scratchpad notes (G8) are **never touched** — that is the
explicit survival channel for anything the agent must not forget. The default
summariser is a deterministic structural digest; an LLM-backed one is pluggable.

### Bounded, self-describing truncation (G2)

Truncation never leaves the model guessing. A truncated result carries explicit
markers so the model can request more without unbounded calls:

- **strings** are sliced with a trailing marker;
- **lists** keep the longest prefix that fits (whole items, never half an item),
  wrapped with `_truncated` / `_original_count`;
- **dicts** keep insertion-order items that fit and expose `available_keys` — the
  keys the model can re-request to see what was dropped.

### Parallel, cached reads (G9 / G11)

Read-only tool calls in a turn are gathered concurrently, and the per-session cache
(G9) is consulted before any execution. Together they cut latency and eliminate
duplicate model-driven calls — efficiency you can see in the eval's repeated-call
metric.

## Where to look

- `reigner/harness/loop.py` — the loop and the guardrail wiring, top to bottom.
- `reigner/harness/oracle.py` — the oracle adapter swap.
- `reigner/harness/compaction.py` — the compaction tiers.
- `reigner/harness/truncation.py` — the bounded-result contract.
- `reigner/harness/state.py` — the budget, prompt assembly, and scratchpad.

The rationale behind these choices lives in
[Principles](../design/principles.md); the hands-on commands are in the
[Usage guide](usage.md).
