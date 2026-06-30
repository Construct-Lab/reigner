"""Single-turn oracle escalation.

The model can call the ``escalate_to_oracle`` pseudo-tool when a question
requires deeper reasoning than the default adapter has produced. The next
*single* iteration is served by ``state.oracle_adapter``; subsequent
iterations revert to ``state.adapter``.

This module owns the mechanism — the adapter swap and the single-turn
revert. The pseudo-tool surface that exposes the escalation to the model
lives in ``tools/pseudo/escalate_to_oracle.py``; it calls :func:`arm` here.
"""

from __future__ import annotations

from reigner.harness.adapters.base import ModelAdapter
from reigner.harness.state import AgentState


class OracleNotConfigured(RuntimeError):
    """Raised when ``arm`` is called but ``state.oracle_adapter`` is None.

    Surfacing misconfiguration early beats falling back to the default model
    silently — the user asked for the oracle.
    """


def arm(state: AgentState) -> None:
    """Mark the next iteration as oracle-served. Idempotent within a turn."""
    if state.oracle_adapter is None:
        raise OracleNotConfigured(
            "escalate_to_oracle requested but state.oracle_adapter is not configured"
        )
    state.oracle_armed = True


def pick_adapter(state: AgentState) -> ModelAdapter:
    """Return the adapter the next ``adapter.call`` should use.

    Returns the oracle adapter if armed, clearing the flag so the iteration
    after this one reverts to the default adapter. The base adapter is the
    fallback in every other case.
    """
    if state.oracle_armed and state.oracle_adapter is not None:
        state.oracle_armed = False
        return state.oracle_adapter  # type: ignore[return-value]
    if state.adapter is None:
        raise RuntimeError("AgentState has no model adapter configured")
    return state.adapter  # type: ignore[return-value]


__all__ = ["OracleNotConfigured", "arm", "pick_adapter"]
