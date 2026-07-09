"""Compose the ROLE: REIGNER.md plus the on-demand skill menu.

The composed ROLE is the *stable* half of the G1 prompt boundary — it must be
byte-identical across a session's iterations so the prompt-cache prefix keeps
hitting. So this module only ever appends the skill **menu** (name + one-line
description): fixed text known at session start. Skill **bodies** never touch
the ROLE; they enter history on demand via the ``load_skill`` tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from reigner.skills.base import Skill

_MENU_HEADER = "## Available skills"
_MENU_PREAMBLE = (
    "These skills carry deeper instructions than fit here. When one is relevant "
    "to the current step, call `load_skill(name=...)` to pull its full guidance "
    "into context, then follow it. Load a skill only when you are about to act "
    "on it."
)


def compose(role_text: str, skills: Sequence[Skill]) -> str:
    """Return REIGNER.md with the skill menu appended (or unchanged if none).

    The menu is a stable block: a header, a one-line preamble telling the model
    how to load a skill, and one ``- name: description`` line per configured
    skill. Nothing here varies per turn.
    """
    if not skills:
        return role_text
    menu_lines = "\n".join(skill.menu_line() for skill in skills)
    block = f"{_MENU_HEADER}\n\n{_MENU_PREAMBLE}\n\n{menu_lines}"
    if not role_text.strip():
        return block
    return f"{role_text.rstrip()}\n\n{block}"


__all__ = ["compose"]
