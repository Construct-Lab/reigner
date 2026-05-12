"""escalate_to_oracle pseudo-tool — single-turn escalation to a stronger model.

The loop (T-05) intercepts the call, emits an `OracleEscalationEvent`, and
swaps the model adapter for one turn. The next turn uses the more capable
oracle model; subsequent turns revert to the primary adapter. Costs are
surfaced in session metadata. SPEC §5.5.

T-05 currently emits the event but defers the adapter swap — see issue #5
brainstorm in `loop.py:_dispatch_pseudo`. T-08 ships the pseudo-tool surface
so the model can call it and plugins/eval can observe the request.

The body raises because dispatch happens before invocation.
"""

from reigner.tools.base import ToolResult, tool


@tool(pseudo=True, readonly=True)
async def escalate_to_oracle(reason: str) -> ToolResult:
    """Escalate the next turn to a more capable model.

    Use this only when the current model has genuinely failed to make
    progress over the last two or three iterations — a question requires
    deeper reasoning than retrieval has provided, or a tradeoff needs more
    careful weighing than the current model has demonstrated. The next turn
    runs on the oracle adapter; subsequent turns revert.

    Do NOT use this as a default. Oracle calls are more expensive and slower.
    They are a valve for genuinely stuck reasoning, not a substitute for
    better tool use. If you have not exhausted retrieval, retrieve first.

    Args:
        reason: One or two sentences explaining what you have tried and why
            the next turn needs more capability. The reason is logged and
            surfaced in eval — be specific.
    """
    raise NotImplementedError(
        "escalate_to_oracle is a pseudo-tool intercepted by the loop; "
        "direct invocation is not supported."
    )
