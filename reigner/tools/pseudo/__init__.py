"""Pseudo-tools — locally-intercepted control verbs for self-managing the loop.

Each pseudo-tool exposes a JSON Schema so the model can call it, but the loop
intercepts the call before invocation. Direct invocation raises
`NotImplementedError`. The four bundled here are the minimum self-management
set: remember (`save_note`), ask (`request_clarification`), escalate
(`escalate_to_oracle`), quit (`stop`).

`PSEUDO_TOOL_NAMES` is the canonical name set the loop's dispatch keys off.
"""

from reigner.tools.pseudo.escalate_to_oracle import escalate_to_oracle
from reigner.tools.pseudo.request_clarification import request_clarification
from reigner.tools.pseudo.save_note import save_note
from reigner.tools.pseudo.stop import stop

PSEUDO_TOOL_NAMES: frozenset[str] = frozenset(
    {"save_note", "request_clarification", "escalate_to_oracle", "stop"}
)

__all__ = [
    "PSEUDO_TOOL_NAMES",
    "escalate_to_oracle",
    "request_clarification",
    "save_note",
    "stop",
]
