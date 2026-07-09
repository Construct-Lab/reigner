"""``clarify_when_ambiguous`` — ask before answering an underspecified question."""

from __future__ import annotations

from reigner.skills.base import Skill


class ClarifyWhenAmbiguous(Skill):
    """Discipline: surface a genuine ambiguity instead of guessing past it."""

    name = "clarify_when_ambiguous"
    description = "Ask a clarifying question when the request is genuinely ambiguous."
    tools_required = ["request_clarification"]

    instructions = """
    When a request has more than one reasonable reading that would lead to
    materially different answers, stop and call `request_clarification` with the
    question and the candidate interpretations. Examples: an entity name that
    matches several artifacts, a metric that exists for multiple periods, a
    comparison with no stated baseline.

    Do not clarify reflexively. If one reading is clearly the intended one, or
    the difference is immaterial to the answer, proceed and note the assumption
    instead. The bar is: would guessing wrong waste the user's time or mislead
    them? Only then ask.
    """
