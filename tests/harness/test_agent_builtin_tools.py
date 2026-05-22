"""Harness.from_config auto-registers SPEC §6.4 pseudo-tools and register_citation.

Issue #64: the four pseudo-tools (save_note, request_clarification,
escalate_to_oracle, stop) plus register_citation are intercepted by the loop
but used to be invisible to the model because they were never registered.
These tests pin down the new auto-registration contract:

  - The four always-on builtins land in the registry on a default config.
  - escalate_to_oracle is gated on an oracle adapter being configured.
  - Profile filters (read_only, eval) operate on the now-registered specs.
  - A user tool that collides on name with a builtin raises loudly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reigner.harness.agent import Harness
from reigner.tools.base import tool
from reigner.tools.registry import ToolRegistrationError

MINIMAL = """\
name: demo
model:
  provider: openai
  name: gpt-4o
"""

ORACLE_SECTION = "oracle:\n  provider: anthropic\n  model: claude-opus-4-7\n"

ALWAYS_ON = {"save_note", "request_clarification", "stop", "register_citation"}


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "reigner.yaml"
    p.write_text(body)
    return p


def test_default_config_registers_four_always_on_builtins(tmp_path: Path) -> None:
    h = Harness.from_config(_write(tmp_path, MINIMAL))
    names = {t.name for t in h.registry}
    assert names >= ALWAYS_ON
    assert "escalate_to_oracle" not in names


def test_escalate_to_oracle_registered_when_oracle_configured(tmp_path: Path) -> None:
    h = Harness.from_config(_write(tmp_path, MINIMAL + ORACLE_SECTION))
    names = {t.name for t in h.registry}
    assert "escalate_to_oracle" in names
    assert names >= ALWAYS_ON


def test_escalate_to_oracle_absent_without_oracle(tmp_path: Path) -> None:
    h = Harness.from_config(_write(tmp_path, MINIMAL))
    assert "escalate_to_oracle" not in {t.name for t in h.registry}


def test_eval_profile_excludes_clarify_and_escalate(tmp_path: Path) -> None:
    h = Harness.from_config(_write(tmp_path, MINIMAL + ORACLE_SECTION))
    names = {a.name for a in h.registry.for_profile("eval")}
    assert "escalate_to_oracle" not in names
    assert "request_clarification" not in names
    assert {"save_note", "stop", "register_citation"} <= names


def test_read_only_profile_includes_all_builtins(tmp_path: Path) -> None:
    h = Harness.from_config(_write(tmp_path, MINIMAL + ORACLE_SECTION))
    names = {a.name for a in h.registry.for_profile("read_only")}
    expected = ALWAYS_ON | {"escalate_to_oracle"}
    assert expected <= names


def test_user_tool_colliding_with_builtin_raises(tmp_path: Path) -> None:
    """Builtins are registered first; a user tool reusing their name must
    raise rather than silently shadow a SPEC §6.4 verb."""

    @tool(readonly=True)
    async def save_note(text: str) -> dict[str, str]:  # noqa: D401 — fixture
        """Fake user tool that collides with the builtin save_note."""
        return {"text": text}

    with pytest.raises(ToolRegistrationError):
        Harness.from_config(_write(tmp_path, MINIMAL), tools=[save_note])
