"""The chat startup banner summarises the loaded project at a glance."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from rich.console import Console

from reigner.cli._banner import render_banner
from reigner.harness.agent import Session

_CONFIG = """\
name: sec-10k-qa
model:
  provider: openai
  name: gpt-4o
  temperature: 0.3
"""


def _render(session: Session, config_path: Path) -> str:
    # Fixed width + no colour so assertions match on plain text, not ANSI.
    console = Console(width=100, force_terminal=False, no_color=True)
    with console.capture() as cap:
        render_banner(console, session, config_path)
    return cap.get()


def test_banner_carries_the_loaded_summary(
    make_session: Callable[..., Session], tmp_path: Path
) -> None:
    config = tmp_path / "reigner.yaml"
    config.write_text(_CONFIG)
    (tmp_path / "REIGNER.md").write_text("# role")

    out = _render(make_session(), config)

    assert "reigner" in out
    assert "sec-10k-qa" in out  # project name
    assert "openai:gpt-4o" in out  # provider:model
    assert "effort medium" in out  # default effort, always shown
    assert "temp 0.3" in out  # temperature shown only because set here
    assert "0 tools" in out  # empty registry on the fake session
    assert "reigner.yaml" in out
    assert "REIGNER.md" in out


def test_banner_flags_a_missing_role_file(
    make_session: Callable[..., Session], tmp_path: Path
) -> None:
    config = tmp_path / "reigner.yaml"
    config.write_text(_CONFIG)  # no REIGNER.md written alongside it

    out = _render(make_session(), config)

    assert "(missing)" in out


def test_banner_never_raises_on_a_bad_config(
    make_session: Callable[..., Session], tmp_path: Path
) -> None:
    config = tmp_path / "reigner.yaml"
    config.write_text("this: is not: valid: reigner config")

    # Must fail open — a broken config prints nothing rather than crashing the REPL.
    out = _render(make_session(), config)

    assert out.strip() == ""
