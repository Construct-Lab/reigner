"""Resolve ``role.skills`` entries into ``Skill`` instances.

An entry in ``reigner.yaml``'s ``role.skills`` is one of two forms:

- **A bare name** (``citation_strict``) — looked up in :data:`BUNDLED_SKILLS`,
  the skills that ship with Reigner.
- **A dotted path** (``myproject.skills:HouseStyle`` or
  ``myproject.skills.HouseStyle``) — imported via
  :func:`reigner.types.import_dotted`, exactly as ``plugins:`` and
  ``tools.custom:`` resolve. This is what makes skills *user-extensible*: a
  project writes its own ``Skill`` subclass and references it by path.

The distinguishing rule is deliberately simple: an entry containing ``.`` or
``:`` is a dotted path; anything else is a bundled name. Bundled names are flat
identifiers, so there is no ambiguity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from reigner.skills.base import Skill
from reigner.skills.citation_strict import CitationStrict
from reigner.skills.clarify_when_ambiguous import ClarifyWhenAmbiguous
from reigner.skills.scratchpad_discipline import ScratchpadDiscipline
from reigner.skills.targeted_retrieval import TargetedRetrieval
from reigner.types import ConfigError, import_dotted

if TYPE_CHECKING:
    from collections.abc import Sequence

BUNDLED_SKILLS: dict[str, type[Skill]] = {
    CitationStrict.name: CitationStrict,
    TargetedRetrieval.name: TargetedRetrieval,
    ClarifyWhenAmbiguous.name: ClarifyWhenAmbiguous,
    ScratchpadDiscipline.name: ScratchpadDiscipline,
}
"""Name -> class for every skill Reigner ships with. Referenced by bare name."""


def _instantiate(obj: object, entry: str) -> Skill:
    """Turn a resolved class-or-instance into a validated ``Skill`` instance."""
    skill = obj() if isinstance(obj, type) else obj
    if not isinstance(skill, Skill):
        raise ConfigError(
            f"skill {entry!r} resolved to {type(skill).__name__}, which is not a "
            "reigner.skills.Skill subclass."
        )
    if not skill.name:
        raise ConfigError(f"skill {entry!r} has an empty `name` — set a unique identifier.")
    return skill


def resolve_skill(entry: str) -> Skill:
    """Resolve one ``role.skills`` entry to a ``Skill`` instance.

    Raises :class:`ConfigError` on an unknown bundled name or a bad dotted path.
    """
    if "." in entry or ":" in entry:
        return _instantiate(import_dotted(entry), entry)
    cls = BUNDLED_SKILLS.get(entry)
    if cls is None:
        known = ", ".join(sorted(BUNDLED_SKILLS))
        raise ConfigError(
            f"unknown skill {entry!r}. Use a bundled name ({known}) or a dotted "
            "path to your own Skill subclass (e.g. 'myproject.skills:HouseStyle')."
        )
    return _instantiate(cls, entry)


def resolve_skills(entries: Sequence[str]) -> list[Skill]:
    """Resolve every ``role.skills`` entry, rejecting duplicate skill names.

    Duplicate names are a config error rather than a silent last-wins: two
    skills answering to the same ``load_skill(name)`` would make loading
    non-deterministic.
    """
    resolved: list[Skill] = []
    seen: set[str] = set()
    for entry in entries:
        skill = resolve_skill(entry)
        if skill.name in seen:
            raise ConfigError(
                f"duplicate skill name {skill.name!r} — two configured skills share "
                "a name, so load_skill could not tell them apart."
            )
        seen.add(skill.name)
        resolved.append(skill)
    return resolved


__all__ = [
    "BUNDLED_SKILLS",
    "resolve_skill",
    "resolve_skills",
]
