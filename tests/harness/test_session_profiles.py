"""Sessions filter the tool surface by profile (SPEC §6.3).

Closes the T-07 integration gap (issue #56): `Harness.session(profile=...)`
used to raise NotImplementedError for anything but "full". With the registry
wired through, `read_only` drops non-readonly customs and `eval` additionally
drops the two pseudo-tools that defeat determinism.
"""

from __future__ import annotations

from pathlib import Path

from reigner.harness.agent import Harness
from reigner.tools.base import tool
from reigner.tools.pseudo import (
    escalate_to_oracle,
    request_clarification,
    save_note,
    stop,
)

MINIMAL = """\
name: demo
model:
  provider: openai
  name: gpt-4o
"""


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "reigner.yaml"
    p.write_text(body)
    return p


@tool(readonly=True)
async def custom_read(q: str) -> dict[str, str]:
    """A read-only custom tool — visible under every profile."""
    return {"q": q}


@tool(readonly=False)
async def custom_write(text: str) -> dict[str, str]:
    """A write custom tool — hidden under read_only and eval."""
    return {"text": text}


def _build_harness(tmp_path: Path) -> Harness:
    """A harness with one readonly custom, one write custom, plus escalate_to_oracle.

    save_note, stop, request_clarification, and register_citation are now auto-
    registered by Harness.from_config; passing them explicitly would collide.
    escalate_to_oracle is gated on oracle-adapter presence, so it is still
    passed in here so the profile-filter assertions can exercise it.
    """
    _ = (save_note, stop, request_clarification)  # imports retained for readers
    h = Harness.from_config(
        _write(tmp_path, MINIMAL),
        tools=[
            custom_read,
            custom_write,
            escalate_to_oracle,
        ],
    )
    return h


def test_full_profile_exposes_every_tool(tmp_path: Path) -> None:
    h = _build_harness(tmp_path)
    names = {a.name for a in h.registry.for_profile("full")}
    assert names == {
        "custom_read",
        "custom_write",
        "save_note",
        "stop",
        "request_clarification",
        "escalate_to_oracle",
        "register_citation",
    }


def test_read_only_profile_excludes_write_customs(tmp_path: Path) -> None:
    h = _build_harness(tmp_path)
    names = {a.name for a in h.registry.for_profile("read_only")}
    assert "custom_write" not in names
    assert {
        "custom_read",
        "save_note",
        "stop",
        "request_clarification",
        "escalate_to_oracle",
    } <= names


def test_eval_profile_also_drops_oracle_and_clarification(tmp_path: Path) -> None:
    h = _build_harness(tmp_path)
    names = {a.name for a in h.registry.for_profile("eval")}
    assert "custom_write" not in names
    assert "escalate_to_oracle" not in names
    assert "request_clarification" not in names
    assert {"custom_read", "save_note", "stop"} <= names


def test_session_carries_profile_into_state(tmp_path: Path) -> None:
    """Session(profile=…) wires the profile through to AgentState."""
    h = _build_harness(tmp_path)
    s = h.session(profile="eval")
    assert s.profile == "eval"
    assert s._state.profile == "eval"
    assert s._state.registry is h.registry


def test_session_profile_does_not_mutate_harness_registry(tmp_path: Path) -> None:
    """Spawning a filtered session leaves the harness's registry untouched."""
    h = _build_harness(tmp_path)
    before = {a.name for a in h.registry.for_profile("full")}
    h.session(profile="read_only")
    h.session(profile="eval")
    after = {a.name for a in h.registry.for_profile("full")}
    assert before == after
