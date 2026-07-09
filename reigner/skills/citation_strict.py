"""``citation_strict`` — refuse numeric claims without a registered citation."""

from __future__ import annotations

from reigner.skills.base import Skill


class CitationStrict(Skill):
    """Discipline: every numeric claim must trace to a registered citation."""

    name = "citation_strict"
    description = "Refuse to make numeric claims without a registered citation."
    tools_required = ["register_citation"]

    instructions = """
    When asserting a numeric value (a figure, a date, a count, a percentage),
    you must, in order:

    1. Have retrieved the value from an artifact in this session — never from
       memory or inference.
    2. Register it with `register_citation`, passing the source and the locator
       that pins the value (e.g. the field path or line).
    3. Reference that source in the answer text so the reader can verify it.

    If you cannot satisfy all three, do not state the number. Say "I don't have
    a verifiable source for that" and offer to search the artifacts or escalate.
    A plausible-sounding number without a citation is a failure, not a partial
    answer.
    """
