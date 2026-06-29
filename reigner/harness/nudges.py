"""Iteration and error nudges (G3, G4).

The agent is steerable, not silent.

Nudges are short synthetic ``user``-role turns the loop appends before the
next adapter call. They never reach the user — they're a budget-aware whisper
to the model.

- **G3 (iteration nudge)**: every ``state.nudge_interval`` iterations, remind
  the model how much budget remains and ask whether it can answer now.
- **G4 (consecutive-error nudge)**: after ``state.max_consecutive_errors`` tool
  errors in a row, ask the model to wrap up gracefully rather than keep
  retrying. The loop only bails out hard if errors *persist* after the nudge.

Both functions return the nudge text (or ``None`` if no nudge is due). The
loop owns the actual ``state.append_turn`` call so all history mutation lives
in one place.
"""

from __future__ import annotations

from reigner.harness.state import AgentState


def iteration_nudge(state: AgentState) -> str | None:
    """G3: every ``nudge_interval`` iterations, return a strategic nudge.

    Fires on iterations 3, 6, 9, ... (with the default interval=3) and skips
    iteration 0 so the first turn isn't preceded by a nudge.
    """
    interval = state.nudge_interval
    if interval <= 0 or state.iterations == 0:
        return None
    if state.iterations % interval != 0:
        return None
    remaining = max(0, state.max_iterations - state.iterations)
    return (
        f"[reigner:nudge] You've used {state.iterations} of {state.max_iterations} "
        f"iterations ({remaining} remaining). Consider whether you can answer with "
        f"the evidence you have, or whether the next tool call will materially change "
        f"that answer."
    )


def error_nudge(state: AgentState) -> str | None:
    """G4: after N consecutive tool errors, return an early-stop nudge.

    Returns ``None`` until the threshold is reached. The loop should inject
    the nudge once and only bail with an ErrorEvent if errors keep coming.
    """
    if state.consecutive_errors() < state.max_consecutive_errors:
        return None
    return (
        f"[reigner:nudge] {state.consecutive_errors()} consecutive tool calls have "
        f"failed. Stop retrying. Either summarize what you have learned so far and "
        f"produce a final answer, or call request_clarification if you need user input."
    )


__all__ = ["error_nudge", "iteration_nudge"]
