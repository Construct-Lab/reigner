"""save_note pseudo-tool — durable scratchpad (G8).

The loop (T-05, `harness/loop.py:_dispatch_pseudo`) intercepts calls before
invocation and appends the text to `AgentState.notes` via `state.add_note`
(T-03). Notes survive history compaction (G5/G10), which is the whole point:
facts the model wants to keep across summarization need a write path that is
not the conversation history.

The body raises so anyone calling this outside the loop (a test, a script)
gets a clear error instead of a silent no-op.
"""

from reigner.tools.base import ToolResult, tool


@tool(pseudo=True, readonly=True)
async def save_note(text: str) -> ToolResult:
    """Save a fact to the durable scratchpad.

    Use this when you have found a specific fact — a value, a date, a citation,
    a file path — that you will need later in this session. Notes survive
    history compaction, so they remain accessible after older turns get
    summarized. Without a note, a fact found early may be lost when context
    pressure forces compaction.

    Do NOT use this to restate the user's question, narrate your plan, or
    summarize your reasoning. Notes are for facts you do not want to re-derive.

    Args:
        text: The fact to remember. One or two sentences. Include enough
            context that the note stands alone (e.g., "Apple FY2024 R&D
            spend: $7.8B per metrics.json:rd_expense").
    """
    raise NotImplementedError(
        "save_note is a pseudo-tool intercepted by the loop; direct invocation is not supported."
    )
