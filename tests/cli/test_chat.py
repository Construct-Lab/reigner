"""Behavior tests for `reigner chat` (T-19).

Covers headless modes (``--print``, ``--print --json``), config error
surfacing, and the interactive REPL via prompt_toolkit's pipe-input harness.
A scripted FakeAdapter from ``tests/cli/conftest.py`` keeps everything
offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reigner.cli.__main__ import app
from reigner.harness.events import from_json

runner = CliRunner()


# ---------------------------------------------------------------------------
# --print
# ---------------------------------------------------------------------------


def test_print_plain_outputs_final_answer_only(patch_build_session) -> None:
    from tests.cli.conftest import _final

    patch_build_session([_final("the answer is 42")])
    result = runner.invoke(app, ["chat", "--print", "what is the answer?"])

    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == "the answer is 42"


def test_print_json_emits_nd_json_event_stream(patch_build_session) -> None:
    from tests.cli.conftest import _final

    patch_build_session([_final("hi")])
    result = runner.invoke(app, ["chat", "--print", "ping", "--json"])

    assert result.exit_code == 0, result.stderr
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert lines, "expected at least one JSON line"

    events = [from_json(ln) for ln in lines]
    # Each line parses; the last is a FinalAnswerEvent.
    from reigner.harness.events import FinalAnswerEvent

    assert isinstance(events[-1], FinalAnswerEvent)
    assert events[-1].text == "hi"

    # Plain text must not leak when --json is set.
    assert "hi" not in result.stdout.replace(json.dumps("hi"), "")


def test_json_without_print_is_usage_error() -> None:
    result = runner.invoke(app, ["chat", "--json"])
    assert result.exit_code == 2
    assert "--json only makes sense with --print" in result.stderr


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


def test_missing_reigner_yaml_errors_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["chat", "--print", "anything"])
    assert result.exit_code == 2
    assert "no reigner.yaml" in result.stderr
    assert "reigner init" in result.stderr


# ---------------------------------------------------------------------------
# Interactive REPL — prompt_toolkit pipe input smoke test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repl_runs_one_query_and_exits(
    make_session, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Drive the REPL through prompt_toolkit's pipe-input + dummy output."""
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from reigner.cli import chat as chat_module
    from tests.cli.conftest import _final

    session = make_session([_final("repl answer")])

    # Pretend stdin is a TTY so the REPL doesn't refuse to start.
    monkeypatch.setattr(chat_module.sys.stdin, "isatty", lambda: True)

    with create_pipe_input() as inp:
        # `ask\n` → submit query.  `/exit\n` → leave the REPL.
        inp.send_text("ask\n/exit\n")

        # Pin prompt_toolkit's defaults to our pipe + dummy output for this test.
        from prompt_toolkit.application import create_app_session

        with create_app_session(input=inp, output=DummyOutput()):
            await chat_module._run_repl(session)

    # The fake adapter recorded one Prompt call → the query made it through.
    assert len(session.harness.adapter.calls) == 1
    # Session's event log has a FinalAnswerEvent for the run.
    from reigner.harness.events import FinalAnswerEvent

    assert any(isinstance(e, FinalAnswerEvent) for e in session.events())


def test_repl_refuses_without_tty(patch_build_session, monkeypatch: pytest.MonkeyPatch) -> None:
    patch_build_session()
    # CliRunner's stdin is not a TTY, so invoking `chat` (no --print) errors.
    result = runner.invoke(app, ["chat"])
    assert result.exit_code == 2
    assert "needs a TTY" in result.stderr
