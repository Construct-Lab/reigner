"""Skill protocol, resolver, composition, and the load_skill tool."""

from __future__ import annotations

import pytest

from reigner.role.compose import compose
from reigner.skills import Skill, resolve_skills
from reigner.skills.registry import BUNDLED_SKILLS
from reigner.tools.skills import build_skill_tools
from reigner.types import ConfigError


class _House(Skill):
    name = "house_style"
    description = "Answer in the org's house voice."
    instructions = """
        Line one.
        Line two.
    """


# ---------------------------------------------------------------------------
# Skill base
# ---------------------------------------------------------------------------


def test_menu_line_is_name_and_description() -> None:
    assert _House().menu_line() == "- house_style: Answer in the org's house voice."


def test_body_dedents_and_strips() -> None:
    assert _House().body() == "Line one.\nLine two."


def test_bundled_skills_all_have_name_and_description() -> None:
    for name, cls in BUNDLED_SKILLS.items():
        skill = cls()
        assert skill.name == name
        assert skill.description
        assert skill.body()


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def test_resolve_bundled_name() -> None:
    [skill] = resolve_skills(["citation_strict"])
    assert skill.name == "citation_strict"


def test_resolve_dotted_path() -> None:
    [skill] = resolve_skills(["tests.skills.test_skills:_House"])
    assert skill.name == "house_style"


def test_resolve_unknown_name_raises() -> None:
    with pytest.raises(ConfigError, match="unknown skill 'nope'"):
        resolve_skills(["nope"])


def test_resolve_bad_dotted_path_raises() -> None:
    with pytest.raises(ConfigError):
        resolve_skills(["tests.skills.test_skills:DoesNotExist"])


def test_resolve_duplicate_name_raises() -> None:
    with pytest.raises(ConfigError, match="duplicate skill name"):
        resolve_skills(["citation_strict", "citation_strict"])


def test_resolve_empty_list_is_empty() -> None:
    assert resolve_skills([]) == []


# ---------------------------------------------------------------------------
# compose
# ---------------------------------------------------------------------------


def test_compose_appends_menu() -> None:
    skills = resolve_skills(["citation_strict", "targeted_retrieval"])
    out = compose("# Identity\nYou are an agent.", skills)
    assert out.startswith("# Identity\nYou are an agent.")
    assert "## Available skills" in out
    assert "- citation_strict:" in out
    assert "- targeted_retrieval:" in out
    assert "load_skill(name" in out  # preamble tells the model how to load


def test_compose_no_skills_returns_role_unchanged() -> None:
    assert compose("ROLE", []) == "ROLE"


def test_compose_empty_role_returns_menu_only() -> None:
    out = compose("", resolve_skills(["citation_strict"]))
    assert out.startswith("## Available skills")


# ---------------------------------------------------------------------------
# load_skill tool
# ---------------------------------------------------------------------------


def test_build_skill_tools_empty_when_no_skills() -> None:
    assert build_skill_tools([]) == []


def test_build_skill_tools_registers_load_skill() -> None:
    [tool] = build_skill_tools(resolve_skills(["citation_strict"]))
    assert tool.name == "load_skill"
    assert tool.readonly is True
    assert tool.pseudo is False  # real tool, not an intercepted verb


@pytest.mark.asyncio
async def test_load_skill_returns_body() -> None:
    [tool] = build_skill_tools(resolve_skills(["citation_strict"]))
    result = await tool.run({"name": "citation_strict"})
    assert result["skill"] == "citation_strict"
    assert "verifiable source" in result["instructions"]


@pytest.mark.asyncio
async def test_load_skill_unknown_name_returns_error() -> None:
    [tool] = build_skill_tools(resolve_skills(["citation_strict"]))
    result = await tool.run({"name": "nope"})
    assert "error" in result
    assert result["available_skills"] == ["citation_strict"]


def test_load_skill_not_intercepted() -> None:
    """The invariant that makes session restore faithful: load_skill flows
    through the normal tool path (and thus the replay stub path), so a resumed
    session replays the *recorded* body rather than re-resolving it."""
    from reigner.harness.loop import INTERCEPTED_TOOL_NAMES

    assert "load_skill" not in INTERCEPTED_TOOL_NAMES
