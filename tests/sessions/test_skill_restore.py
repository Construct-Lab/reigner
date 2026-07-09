"""A session that loaded a skill restores the *recorded* body faithfully.

The design property (issue #30): ``load_skill`` is a real tool, so its
ToolCall/ToolResult pair is logged and reconstruction replays the recorded body
through the stub-tool path — even if the skill is later removed from
``role.skills``. This is the reproducibility guarantee for shipped agents.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reigner.config import SessionsConfig, SettingsConfig
from reigner.harness.adapters.base import ToolCall
from reigner.harness.agent import Harness, Session
from reigner.harness.events import Event
from reigner.role.compose import compose
from reigner.skills import resolve_skills
from reigner.tools.registry import ToolRegistry
from reigner.tools.skills import build_skill_tools
from tests.harness.test_loop import FakeAdapter, _final, _tool_action


def _harness(tmp_path: Path, *, with_skill: bool, actions: list[object]) -> Harness:
    """Build a Harness with or without the citation_strict skill wired.

    ``with_skill=False`` proves restore does not depend on the live registry.
    """
    skills = resolve_skills(["citation_strict"]) if with_skill else []
    registry = ToolRegistry()
    for t in build_skill_tools(skills):
        registry.register(t)
    return Harness(
        adapter=FakeAdapter(actions=list(actions)),
        settings=SettingsConfig(),
        sessions=SessionsConfig(store_path=str(tmp_path / "sessions"), auto_save=True),
        registry=registry,
        role=compose("ROLE", skills),
    )


async def _drain(session: Session, query: str) -> list[Event]:
    return [ev async for ev in session.run_stream(query)]


@pytest.mark.asyncio
async def test_loaded_skill_body_lands_in_history(tmp_path: Path) -> None:
    h = _harness(
        tmp_path,
        with_skill=True,
        actions=[
            _tool_action(ToolCall(id="c1", name="load_skill", args={"name": "citation_strict"})),
            _final("done"),
        ],
    )
    session = h.session()
    await _drain(session, "what is the R&D spend?")

    tool_turns = [t for t in session.history() if t.role == "tool"]
    assert any("verifiable source" in t.content for t in tool_turns)


@pytest.mark.asyncio
async def test_restore_replays_recorded_body_even_after_skill_removed(tmp_path: Path) -> None:
    # Run with the skill wired; the body is recorded to the session log.
    h = _harness(
        tmp_path,
        with_skill=True,
        actions=[
            _tool_action(ToolCall(id="c1", name="load_skill", args={"name": "citation_strict"})),
            _final("done"),
        ],
    )
    original = h.session()
    await _drain(original, "q?")
    original_tool_turns = [t.content for t in original.history() if t.role == "tool"]

    # Reload through a harness where the skill is GONE from config/registry.
    h2 = _harness(tmp_path, with_skill=False, actions=[_final("later")])
    loaded = Session.load(original.id, harness=h2)

    reloaded_tool_turns = [t.content for t in loaded.history() if t.role == "tool"]
    # The recorded body is replayed byte-for-byte, not re-resolved.
    assert reloaded_tool_turns == original_tool_turns
    assert any("verifiable source" in c for c in reloaded_tool_turns)
