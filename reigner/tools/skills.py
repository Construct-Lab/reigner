"""The ``load_skill`` tool — on-demand progressive disclosure of skill bodies.

``load_skill`` is a real, read-only tool bound to the project's resolved
skills. When the model calls it, the skill's body (its full instructions) is
returned as the tool result and the loop appends that result to *history* — the
dynamic half of the G1 prompt boundary. The stable ROLE (which carries only the
skill menu) is never rewritten, so every adapter's prompt-cache prefix keeps
hitting. This is exactly how a body enters context "the way harnesses do it":
a tool call whose result is the instruction block.

It is deliberately *not* a locally-intercepted pseudo-tool. Because it flows
through the normal tool path, session reconstruction replays the *recorded*
body via the stub-tool path (see :mod:`reigner.sessions.replay`) — so a resumed
session carries the exact instructions the model saw, even if the skill was
later removed from ``role.skills``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from reigner.tools.base import RunnableToolAdapter, ToolResult, to_runnable, tool

if TYPE_CHECKING:
    from collections.abc import Sequence

    from reigner.skills.base import Skill


def build_skill_tools(skills: Sequence[Skill]) -> list[RunnableToolAdapter]:
    """Build the ``load_skill`` tool bound to ``skills`` (empty list if none).

    Returns a single-tool list so it slots into the harness wiring the same way
    ``build_artifact_tools`` / ``build_search_tools`` do. With no skills
    configured there is nothing to load, so no tool is registered — keeping the
    surface clean for skill-less projects.
    """
    if not skills:
        return []

    by_name: dict[str, Skill] = {skill.name: skill for skill in skills}
    catalog = "; ".join(f"{s.name} — {s.description}" for s in skills)

    @tool(
        readonly=True,
        description=(
            "Load a skill's full instructions into context by name, then follow "
            "them. Call this only when the skill is relevant to your current "
            f"step. Available skills: {catalog}."
        ),
    )
    async def load_skill(name: str) -> ToolResult:  # noqa: RUF029 — async is the tool contract
        skill = by_name.get(name)
        if skill is None:
            return {
                "error": f"unknown skill: {name!r}",
                "available_skills": sorted(by_name),
            }
        return {"skill": skill.name, "instructions": skill.body()}

    return [to_runnable(load_skill)]


__all__ = ["build_skill_tools"]
