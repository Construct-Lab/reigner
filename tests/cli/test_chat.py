"""Behavior tests for `reigner chat`.

Covers headless modes (``--print``, ``--print --json``), config error
surfacing, and the interactive REPL via prompt_toolkit's pipe-input harness.
A scripted FakeAdapter from ``tests/cli/conftest.py`` keeps everything
offline.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
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


def test_print_plain_reports_fatal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from reigner.cli import chat as chat_module
    from reigner.harness.events import ErrorEvent

    class ErrorSession:
        async def run_stream(self, query):
            yield ErrorEvent(
                seq=1,
                session_id="test",
                turn=1,
                error="adapter: openai package not installed",
                recoverable=False,
            )

    monkeypatch.setattr(chat_module, "_build_session", lambda _path: ErrorSession())
    result = runner.invoke(app, ["chat", "--print", "anything"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "error: adapter: openai package not installed\n"


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


async def _wait_for(predicate, *, timeout: float = 2.0) -> bool:
    """Poll ``predicate`` on the running event loop until true or timeout."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return False


@dataclass
class _BlockingFirstAdapter:
    """Adapter whose first ``call`` blocks on an Event, then scripts actions.

    Lets a test hold the first model call open so a mid-run keystroke has a
    real in-flight run to land on, then release it to let the loop finish.
    """

    actions: list
    release: asyncio.Event
    name: str = "fake"
    model: str = "fake-1"
    supports_prompt_caching: bool = False
    calls: list = field(default_factory=list)
    _blocked: bool = False

    async def call(self, prompt, tools):  # type: ignore[no-untyped-def]
        self.calls.append(prompt)
        if not self._blocked:
            self._blocked = True
            await self.release.wait()
        nxt = self.actions.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


@pytest.mark.asyncio
async def test_repl_runs_one_query(make_session, monkeypatch: pytest.MonkeyPatch) -> None:
    """A submitted query runs to a final answer; the prompt stays live after."""
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from reigner.cli import chat as chat_module
    from reigner.harness.events import FinalAnswerEvent
    from tests.cli.conftest import _final

    session = make_session([_final("repl answer")])
    monkeypatch.setattr(chat_module.sys.stdin, "isatty", lambda: True)

    with create_pipe_input() as inp:
        inp.send_text("ask\n")
        with create_app_session(input=inp, output=DummyOutput()):
            repl_task = asyncio.ensure_future(
                chat_module._run_repl(session, Path("no-banner.yaml"))
            )
            done = await _wait_for(
                lambda: any(isinstance(e, FinalAnswerEvent) for e in session.events())
            )
            repl_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(repl_task, timeout=2.0)

    assert done, "run never produced a final answer"
    assert len(session.harness.adapter.calls) == 1


@pytest.mark.asyncio
async def test_repl_exit_command(make_session, monkeypatch: pytest.MonkeyPatch) -> None:
    """`/exit` typed at the idle prompt leaves the REPL without a model call."""
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from reigner.cli import chat as chat_module

    session = make_session()
    monkeypatch.setattr(chat_module.sys.stdin, "isatty", lambda: True)

    with create_pipe_input() as inp:
        inp.send_text("/exit\n")
        with create_app_session(input=inp, output=DummyOutput()):
            await asyncio.wait_for(
                chat_module._run_repl(session, Path("no-banner.yaml")), timeout=2.0
            )

    assert session.harness.adapter.calls == []


@pytest.mark.asyncio
async def test_repl_queues_next_question_midrun(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mid-run Enter queues the typed text as a separate next question.

    The first run answers on its own, then the queued question runs as a fresh
    turn — two distinct model calls, two final answers — rather than folding
    into the first run's trajectory.
    """
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from reigner.cli import chat as chat_module
    from reigner.config import SettingsConfig
    from reigner.harness.agent import Harness
    from reigner.harness.events import FinalAnswerEvent, SteeringAcceptedEvent
    from tests.cli.conftest import _final

    release = asyncio.Event()
    # One scripted final answer per question; the blocking adapter parks the
    # first call so q2 can be typed while q1 is genuinely in flight.
    adapter = _BlockingFirstAdapter(
        actions=[_final("answer-1"), _final("answer-2")], release=release
    )
    session = Harness(adapter=adapter, role="TEST", settings=SettingsConfig()).session()

    monkeypatch.setattr(chat_module.sys.stdin, "isatty", lambda: True)

    with create_pipe_input() as inp, create_app_session(input=inp, output=DummyOutput()):
        repl_task = asyncio.ensure_future(chat_module._run_repl(session, Path("no-banner.yaml")))

        inp.send_text("q1\n")
        assert await _wait_for(lambda: bool(adapter.calls)), "q1 never started"

        # Plain Enter mid-run → queued as the NEXT question, not a steer.
        inp.send_text("q2\n")

        # Release q1; it answers, then q2 runs on its own as a second turn.
        release.set()
        got_both = await _wait_for(
            lambda: sum(isinstance(e, FinalAnswerEvent) for e in session.events()) >= 2
        )
        assert got_both, "second question never ran as its own turn"
        answers = [e.text for e in session.events() if isinstance(e, FinalAnswerEvent)]
        assert answers == ["answer-1", "answer-2"]
        assert len(adapter.calls) == 2
        # It was a separate question, never a steer of q1's run.
        assert not any(isinstance(e, SteeringAcceptedEvent) for e in session.events())
        assert session._state.pending_steering == []

        repl_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(repl_task, timeout=2.0)


@pytest.mark.asyncio
async def test_repl_captures_midrun_steer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression + steer: Alt+Enter (Esc-then-Enter) steers the in-flight run.

    The prompt must stay live during the run (it did not before — the prompt
    app stopped before ``await task``), so the typed text reaches the steering
    queue and is drained as a user turn at the loop's next boundary.
    """
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from reigner.cli import chat as chat_module
    from reigner.config import SettingsConfig
    from reigner.harness.adapters.base import ModelAction, TokenUsage, ToolCall
    from reigner.harness.agent import Harness
    from reigner.harness.events import SteeringAcceptedEvent
    from tests.cli.conftest import _final

    release = asyncio.Event()
    # Iteration 1 issues a pseudo-tool (save_note) so the loop continues past
    # the in-flight model call to a second boundary where the steer drains.
    note_action = ModelAction(
        is_final_answer=False,
        text=None,
        tool_calls=[ToolCall(id="c1", name="save_note", args={"text": "noting"})],
        usage=TokenUsage.empty(),
        stop_reason="tool_calls",
    )
    adapter = _BlockingFirstAdapter(actions=[note_action, _final("done")], release=release)
    session = Harness(adapter=adapter, role="TEST", settings=SettingsConfig()).session()

    monkeypatch.setattr(chat_module.sys.stdin, "isatty", lambda: True)

    with create_pipe_input() as inp, create_app_session(input=inp, output=DummyOutput()):
        repl_task = asyncio.ensure_future(chat_module._run_repl(session, Path("no-banner.yaml")))

        # Submit the query, then wait until its model call is genuinely in
        # flight — the blocking adapter records the call, then parks on
        # `release`. Only now is the run "running".
        inp.send_text("ask\n")
        started = await _wait_for(lambda: bool(adapter.calls))
        assert started, "first model call never started"

        # Steer WHILE the run is in flight via Alt+Enter — sent on the wire as
        # ESC + CR ("\x1b\r"), which is also how "Esc then Enter" arrives. The
        # buffer text must reach the steering queue, not the question queue.
        inp.send_text("redirect\x1b\r")
        captured = await _wait_for(lambda: bool(session._state.pending_steering))
        assert captured, "mid-run steer was not captured"
        assert session._state.pending_steering[0] == ("redirect", "queue")

        # Release the blocked call; the queued steer drains at the next turn.
        release.set()
        drained = await _wait_for(
            lambda: any(isinstance(e, SteeringAcceptedEvent) for e in session.events())
        )
        assert drained, "queued steer was not drained at the next boundary"
        steer_ev = next(e for e in session.events() if isinstance(e, SteeringAcceptedEvent))
        assert steer_ev.mode == "queue"
        assert steer_ev.message == "redirect"

        repl_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(repl_task, timeout=2.0)


def test_repl_refuses_without_tty(patch_build_session, monkeypatch: pytest.MonkeyPatch) -> None:
    patch_build_session()
    # CliRunner's stdin is not a TTY, so invoking `chat` (no --print) errors.
    result = runner.invoke(app, ["chat"])
    assert result.exit_code == 2
    assert "needs a TTY" in result.stderr


# ---------------------------------------------------------------------------
# Slash commands: /help + Tab completion
# ---------------------------------------------------------------------------


def _completions(text: str) -> list[str]:
    from prompt_toolkit.document import Document

    from reigner.cli.chat import _SlashCompleter

    doc = Document(text, len(text))
    return [c.text for c in _SlashCompleter().get_completions(doc, None)]


def test_slash_completer_lists_all_commands() -> None:
    from reigner.cli.chat import _COMMANDS

    assert _completions("/") == list(_COMMANDS)


def test_slash_completer_filters_on_prefix() -> None:
    # "/ex" narrows to the two commands that start with it.
    assert _completions("/ex") == ["/expand", "/exit"]


def test_slash_completer_ignores_plain_queries() -> None:
    # A normal question never pops the menu.
    assert _completions("what is the revenue") == []


def test_slash_completions_carry_descriptions() -> None:
    from prompt_toolkit.document import Document

    from reigner.cli.chat import _COMMANDS, _SlashCompleter

    doc = Document("/help", len("/help"))
    (comp,) = _SlashCompleter().get_completions(doc, None)
    # display_meta doubles as inline docs — must match the single command table.
    assert comp.display_meta_text == _COMMANDS["/help"]


def _buffer_with_menu(text: str):
    """A prompt_toolkit Buffer holding ``text`` with its completion menu open."""
    from prompt_toolkit.buffer import Buffer, CompletionState
    from prompt_toolkit.document import Document

    from reigner.cli.chat import _SlashCompleter

    buf = Buffer(document=Document(text, len(text)))
    comps = list(_SlashCompleter().get_completions(buf.document, None))
    buf.complete_state = (
        CompletionState(original_document=buf.document, completions=comps) if comps else None
    )
    return buf


def test_enter_accepts_partial_command_from_open_menu() -> None:
    from reigner.cli.chat import _accept_open_completion

    buf = _buffer_with_menu("/e")
    # Menu open on a partial → Enter accepts (first match) instead of submitting.
    assert _accept_open_completion(buf) is True
    assert buf.text == "/expand"


def test_enter_runs_a_fully_typed_command() -> None:
    from reigner.cli.chat import _accept_open_completion

    buf = _buffer_with_menu("/help")
    # Already a complete command → don't intercept; let Enter submit and run it.
    assert _accept_open_completion(buf) is False
    assert buf.text == "/help"


def test_enter_submits_a_plain_query() -> None:
    from reigner.cli.chat import _accept_open_completion

    buf = _buffer_with_menu("what is revenue")
    # No menu on a normal question → Enter submits as usual.
    assert _accept_open_completion(buf) is False


def test_help_lists_every_slash_command() -> None:
    from rich.console import Console

    from reigner.cli.chat import _COMMANDS, _print_help

    console = Console(width=80, force_terminal=False, no_color=True)
    with console.capture() as cap:
        _print_help(console)
    out = cap.get()

    for name in _COMMANDS:
        assert name in out
    # The non-slash chords show up too.
    assert "Enter" in out
    assert "Ctrl+C" in out
