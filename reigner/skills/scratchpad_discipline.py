"""``scratchpad_discipline`` — when and how to use save_note."""

from __future__ import annotations

from reigner.skills.base import Skill


class ScratchpadDiscipline(Skill):
    """Discipline: persist hard-won facts so compaction can't lose them."""

    name = "scratchpad_discipline"
    description = "Save durable facts with save_note so they survive history compaction."
    tools_required = ["save_note"]

    instructions = """
    Use `save_note` to persist a specific fact the moment you find it — a value,
    a date, a citation id, a file path you will need later this session. Notes
    survive history compaction, so a fact recorded early remains available even
    after older turns are summarized away.

    Write notes that stand alone: include enough context that the note is
    meaningful without the surrounding conversation (e.g. "Apple FY2024 R&D
    spend: $7.8B per metrics.json:rd_expense"), not "found it: 7.8".

    Do not narrate with notes. They are not for restating the question,
    outlining your plan, or summarizing reasoning — only for facts you do not
    want to re-derive.
    """
