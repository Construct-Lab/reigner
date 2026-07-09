"""The ``Skill`` base class — an on-demand-loaded instruction module.

A skill is two things at two different times:

- **A menu line** (name + one-line description) composed into the ROLE at
  session start. This is always present, always cached — it is how the model
  learns the skill exists. See :meth:`Skill.menu_line`.
- **A body** (the full instructions) that enters the conversation *only* when
  the model calls ``load_skill(name)``. The body lands in history as a tool
  result, never in the stable ROLE, so the prompt-cache prefix is never
  rewritten. See :meth:`Skill.body`.

Authoring a skill is subclassing and setting class attributes::

    class HouseStyle(Skill):
        name = "house_style"
        description = "Answer in the org's house voice and format."
        tools_required = []
        instructions = '''
        Open with the headline finding in one sentence...
        '''

Reference such a skill from ``reigner.yaml`` by dotted path
(``myproject.skills:HouseStyle``); bundled skills are referenced by bare name.
"""

from __future__ import annotations

import textwrap
from typing import Any, ClassVar


class Skill:
    """Base class for a composable, on-demand instruction module.

    Subclasses set the class attributes below. Instances are cheap and hold no
    per-session state — the resolver builds one per configured skill and the
    ``load_skill`` tool closes over them.
    """

    name: ClassVar[str] = ""
    """Stable identifier the model uses to load the skill. Must be unique
    across a project's configured skills and is what the model passes to
    ``load_skill(name=...)``."""

    description: ClassVar[str] = ""
    """One-line summary shown in the ROLE menu. This is the model's only cue
    for *when* to load the skill, so make it a crisp trigger, not a title."""

    instructions: ClassVar[str] = ""
    """The full instruction block, revealed only on load. May be indented as a
    triple-quoted literal — :meth:`body` dedents and strips it."""

    tools_required: ClassVar[list[str]] = []
    """Tool names the skill's instructions assume exist. Validated against the
    harness registry at build time so a skill can't reference a tool the
    project didn't wire up."""

    examples: ClassVar[list[Any]] = []
    """Optional few-shot examples. Carried but not composed into :meth:`body`
    in v0 — kept so a project can render them without a schema change."""

    def menu_line(self) -> str:
        """Return the single ROLE menu line: ``- <name>: <description>``."""
        return f"- {self.name}: {self.description}"

    def body(self) -> str:
        """Return the instruction block appended to history when loaded.

        Dedented and stripped so a triple-quoted, indented ``instructions``
        literal reads cleanly in the model's context.
        """
        return textwrap.dedent(self.instructions).strip()


__all__ = ["Skill"]
