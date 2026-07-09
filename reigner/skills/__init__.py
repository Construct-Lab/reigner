"""Skills — on-demand-loaded instruction modules composed into the ROLE menu.

A skill contributes a one-line menu entry to the ROLE (always present, always
cached) and a body that the model pulls into context on demand via the
``load_skill`` tool. Author one by subclassing :class:`Skill`; reference bundled
skills by bare name and your own by dotted path in ``reigner.yaml``'s
``role.skills``.
"""

from reigner.skills.base import Skill
from reigner.skills.registry import BUNDLED_SKILLS, resolve_skill, resolve_skills

__all__ = [
    "BUNDLED_SKILLS",
    "Skill",
    "resolve_skill",
    "resolve_skills",
]
