"""stop pseudo-tool — graceful early termination of the session.

The loop intercepts the call, appends `reason` as an assistant turn, emits a
`FinalAnswerEvent` with `text=reason` and `metadata={"stop": True}`, and sets
`state.done = True`. The session ends without a forced final-answer
hallucination.

The body raises because dispatch happens before invocation.
"""

from reigner.tools.base import ToolResult, tool


@tool(pseudo=True, readonly=True)
async def stop(reason: str) -> ToolResult:
    """End the session, with this text as the final answer.

    Use this when you have a complete answer to give the user, OR when you
    have determined the question cannot be answered with the tools and
    information available. In either case, the `reason` becomes the final
    answer text — write it as the response you want the user to read.

    Do NOT use this to give up at the first sign of difficulty. Try
    retrieval, try alternative phrasings, save notes about what is missing.
    Stop is the final action, not the first.

    Args:
        reason: The final answer. If you found an answer, this is it
            (well-formed prose, with citations if applicable). If you could
            not answer, explain what is missing and what you tried.
    """
    raise NotImplementedError(
        "stop is a pseudo-tool intercepted by the loop; direct invocation is not supported."
    )
