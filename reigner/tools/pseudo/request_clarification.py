"""request_clarification pseudo-tool — pause the loop to ask the user.

The loop intercepts the call, emits a `ClarificationEvent` carrying the
question and any candidates, and sets `state.done = True` to pause the
session. The UI (CLI, web, MCP) renders the question and routes the user's
reply back as the next turn.

The body raises because dispatch happens before invocation.
"""

from reigner.tools.base import ToolResult, tool


@tool(pseudo=True, readonly=True)
async def request_clarification(question: str, candidates: list[str]) -> ToolResult:
    """Ask the user a clarifying question and pause the session.

    Use this when the user's request is ambiguous in a way that retrieval and
    reasoning cannot resolve — e.g., the question references "the report" but
    several reports exist, or asks about a year that could be fiscal or
    calendar. Asking is preferable to guessing and producing a wrong answer
    that looks confident.

    Do NOT use this every time something is mildly under-specified. Try
    retrieval first; only ask when the ambiguity blocks progress. Each
    clarification ends the current turn, so use it deliberately.

    Args:
        question: The single, specific question to ask the user. One sentence.
            Avoid stacking multiple questions into one call.
        candidates: Concrete options the user can pick from, if applicable
            (e.g., ["FY2023", "FY2024"]). Pass an empty list for open-ended
            questions where any answer is acceptable.
    """
    raise NotImplementedError(
        "request_clarification is a pseudo-tool intercepted by the loop; "
        "direct invocation is not supported."
    )
