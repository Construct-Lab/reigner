"""`reigner chat` — interactive REPL and headless one-shot modes.

Three modes from one Typer command:

- ``reigner chat``                       interactive REPL with steering.
- ``reigner chat --print "<q>"``         one-shot; stdout = final answer text.
- ``reigner chat --print "<q>" --json``  one-shot; ND-JSON of every event.

The REPL streams the harness event protocol. The prompt stays live
while a run is in flight, giving two distinct mid-run actions:

- **Enter** queues the typed text as the *next question* — the current run
  answers on its own, then the queued question runs as a fresh turn (type-ahead,
  like queuing a follow-up in Claude Code / ChatGPT).
- **Alt+Enter** (or **Esc then Enter**, which needs no Option-as-Meta) *steers*
  the in-flight run: the text folds into the current loop as a user turn at its
  next boundary, bending this answer rather than starting a new one.

Idle Enter submits a fresh query. There is intentionally no mid-turn preemption
— neither action aborts the in-flight model call.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from pathlib import Path
from typing import Any

import typer
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea
from prompt_toolkit.widgets import base as _ptk_widgets
from rich.console import Console

from reigner.cli._env import load_project_env
from reigner.cli._render import TurnRenderer
from reigner.harness.agent import Harness, Session
from reigner.harness.events import (
    ClarificationEvent,
    ErrorEvent,
    FinalAnswerEvent,
    to_json,
)
from reigner.types import ConfigError

_DEFAULT_CONFIG = "reigner.yaml"

# Braille spinner frames for the composer title while a run is in flight.
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Exit codes (conventional values):
#   0 — final answer produced
#   1 — runtime error (loop error event, no final answer)
#   2 — usage error (missing config, clarification in --print mode)
EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2


@contextlib.contextmanager
def _rounded_border() -> Any:
    """Swap prompt_toolkit's square frame corners for rounded ones, then restore.

    ``Frame`` reads the module-level ``Border`` characters when it builds its
    windows, so setting the corners for the duration of construction bakes
    rounded glyphs into the frame — matching the rich answer panel below it. The
    swap is synchronous and immediately reverted, so no other frame sees it.
    """
    border = _ptk_widgets.Border
    saved = (border.TOP_LEFT, border.TOP_RIGHT, border.BOTTOM_LEFT, border.BOTTOM_RIGHT)
    border.TOP_LEFT, border.TOP_RIGHT, border.BOTTOM_LEFT, border.BOTTOM_RIGHT = "╭", "╮", "╰", "╯"
    try:
        yield
    finally:
        border.TOP_LEFT, border.TOP_RIGHT, border.BOTTOM_LEFT, border.BOTTOM_RIGHT = saved


def register(app: typer.Typer) -> None:
    """Register the ``chat`` command on the given Typer app."""
    app.command("chat")(_chat)


def _chat(
    print_query: str | None = typer.Option(
        None,
        "--print",
        metavar="QUERY",
        help="One-shot mode: run QUERY and exit. Stdout is the final answer text.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="With --print: emit ND-JSON of every event instead of plain text.",
    ),
    config: str = typer.Option(
        _DEFAULT_CONFIG,
        "--config",
        "-c",
        help="Path to reigner.yaml (defaults to ./reigner.yaml).",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Stream every tool call instead of collapsing retrieval to one line.",
    ),
) -> None:
    """Interactive chat REPL, or a one-shot run with ``--print``."""
    if json_output and print_query is None:
        typer.echo("✗ --json only makes sense with --print", err=True)
        raise typer.Exit(EXIT_USAGE)

    session = _build_session(Path(config))

    if print_query is not None:
        code = asyncio.run(_run_print(session, print_query, json_output=json_output))
        raise typer.Exit(code)

    asyncio.run(_run_repl(session, verbose=verbose))


# ---------------------------------------------------------------------------
# Session construction
# ---------------------------------------------------------------------------


def _build_session(config_path: Path) -> Session:
    if not config_path.exists():
        typer.echo(
            f"✗ no {config_path} in {config_path.parent.resolve()} — "
            f"run `reigner init <name> --blank` first",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)
    load_project_env(config_path)
    try:
        harness = Harness.from_config(config_path)
    except ConfigError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(EXIT_USAGE) from e
    return harness.session()


# ---------------------------------------------------------------------------
# --print modes
# ---------------------------------------------------------------------------


async def _run_print(session: Session, query: str, *, json_output: bool) -> int:
    """Drive one query in headless mode. Returns the process exit code."""
    final: FinalAnswerEvent | None = None
    saw_clarification = False
    saw_error = False
    async for event in session.run_stream(query):
        if json_output:
            print(to_json(event), flush=True)
        if isinstance(event, FinalAnswerEvent):
            final = event
        elif isinstance(event, ClarificationEvent):
            saw_clarification = True
        elif isinstance(event, ErrorEvent) and not event.recoverable:
            saw_error = True

    if not json_output and final is not None:
        print(final.text)

    if final is not None:
        return EXIT_OK
    if saw_clarification:
        if not json_output:
            typer.echo(
                "✗ loop ended on a clarification — use interactive mode to answer",
                err=True,
            )
        return EXIT_USAGE
    if saw_error:
        return EXIT_RUNTIME
    return EXIT_RUNTIME


# ---------------------------------------------------------------------------
# Interactive REPL
# ---------------------------------------------------------------------------


async def _run_repl(session: Session, *, verbose: bool = False) -> None:
    """Interactive REPL. Bottom prompt is always live; output streams above it."""
    if not sys.stdin.isatty():
        typer.echo(
            '✗ interactive chat needs a TTY — use `reigner chat --print "<query>"` '
            "for non-interactive runs",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    console = Console()
    running = asyncio.Event()
    current_task: dict[str, asyncio.Task[None] | None] = {"task": None}
    input_q: asyncio.Queue[str] = asyncio.Queue()
    # Shared REPL UI state: whether retrieval detail streams live, and the most
    # recent turn's renderer so `/expand` can reprint its collapsed detail.
    ui: dict[str, Any] = {"verbose": verbose, "last": None}

    kb = KeyBindings()

    @kb.add("enter")
    def _on_enter(event: Any) -> None:
        # Idle: submit the query (the consumer runs it). Mid-run: queue it as
        # the NEXT question — the current run answers on its own, then the
        # consumer pulls this one and runs it as a fresh turn (type-ahead).
        buf = event.app.current_buffer
        text = buf.text.strip()
        buf.reset()
        if not text:
            return
        if text in {"/exit", "/quit"}:
            event.app.exit()
            return
        if text == "/verbose":
            ui["verbose"] = not ui["verbose"]
            state = "on — tool calls stream live" if ui["verbose"] else "off — retrieval collapses"
            console.print(f"[dim]· verbose {state}[/dim]")
            return
        if text == "/expand":
            last: TurnRenderer | None = ui["last"]
            if last is None or not last.print_detail():
                console.print("[dim]· nothing to expand yet[/dim]")
            return
        input_q.put_nowait(text)
        if running.is_set():
            console.print(f"[dim]⌁ queued — runs after the current answer:[/dim] {text}")

    @kb.add("escape", "enter")
    def _on_steer(event: Any) -> None:
        # Alt+Enter — or Esc then Enter, which works on every terminal even
        # without Option-as-Meta. Steers the IN-FLIGHT run: the text folds into
        # the current loop as a user turn at its next boundary, bending this
        # answer rather than starting a new one. No effect when idle.
        buf = event.app.current_buffer
        text = buf.text.strip()
        if not text or not running.is_set():
            return
        buf.reset()
        asyncio.ensure_future(session.steer(text, "queue"))

    @kb.add("c-d")
    def _on_ctrl_d(event: Any) -> None:
        # Idle on an empty buffer: EOF → quit. Mid-run: swallow it so a stray
        # Ctrl+D doesn't tear down the live prompt.
        if running.is_set():
            return
        if not event.app.current_buffer.text:
            event.app.exit(exception=EOFError())

    @kb.add("c-c")
    def _on_ctrl_c(event: Any) -> None:
        task = current_task["task"]
        if running.is_set() and task is not None and not task.done():
            task.cancel()
        else:
            event.app.exit(exception=KeyboardInterrupt())

    # The composer is a bordered box (a Frame) around the input, rendered as a
    # non-full-screen Application so scrollback still flows above it via
    # patch_stdout. The Frame title doubles as a live status line: while a run is
    # in flight it shows a spinner + the renderer's tool/elapsed status (redrawn
    # in place by prompt_toolkit — no scrollback conflict), which is the movement
    # collapsed mode can't stream above the prompt.
    #
    # multiline + wrap_lines so a long question wraps and the box grows downward
    # (up to a cap) instead of scrolling off the right edge. Enter still submits:
    # the explicit ``enter`` key binding above overrides the buffer's default
    # newline-on-Enter. (There is deliberately no separate insert-newline chord —
    # Esc/Alt+Enter is already bound to steering, and a chat prompt is one
    # thought per submit.)
    input_area = TextArea(
        prompt="› ",
        multiline=True,
        wrap_lines=True,
        height=Dimension(min=1, max=10),
    )

    def _title() -> Any:
        if not running.is_set():
            return [("class:frame.label", " ask ")]
        frame = _SPINNER[int(time.monotonic() * 10) % len(_SPINNER)]
        last: TurnRenderer | None = ui["last"]
        status = last.live_status() if last is not None else "working"
        return [("class:frame.label", f" {frame} {status} · esc-enter to steer ")]

    with _rounded_border():
        composer = Frame(input_area, title=_title)
    app: Application[str] = Application(
        layout=Layout(composer),
        key_bindings=kb,
        style=Style.from_dict({"frame.border": "ansimagenta", "frame.label": "ansimagenta bold"}),
        full_screen=False,
        mouse_support=False,
        erase_when_done=True,
        refresh_interval=0.2,  # keep the spinner / elapsed in the title moving
    )

    console.print(
        "[dim]reigner chat — Enter submits (mid-run: queues your next "
        "question); Alt+Enter / Esc-then-Enter steers the running answer; "
        "/expand shows the last retrieval, /verbose toggles live tool calls; "
        "Ctrl+C cancels; /exit or Ctrl+D to quit.[/dim]"
    )

    async def _consume() -> None:
        # Drive runs off the input queue while the prompt stays live. Output
        # streams above the prompt via the surrounding patch_stdout. Each query
        # is echoed as it starts so type-ahead questions are easy to follow.
        while True:
            query = await input_q.get()
            console.print(f"[dim]›[/dim] {query}")
            running.set()
            run_task = asyncio.ensure_future(
                _drive_run(session, query, console, ui, verbose=ui["verbose"])
            )
            current_task["task"] = run_task
            try:
                await run_task
            except asyncio.CancelledError:
                running.clear()
                current_task["task"] = None
                if run_task.cancelled():
                    # Ctrl+C cancelled this run — report and keep the REPL alive.
                    console.print("[yellow]· run cancelled[/yellow]")
                    continue
                # The consumer itself is being torn down (REPL shutdown).
                run_task.cancel()
                raise
            running.clear()
            current_task["task"] = None

    with patch_stdout(raw=True):
        consumer = asyncio.ensure_future(_consume())
        try:
            await app.run_async()
        except (EOFError, KeyboardInterrupt):
            pass
        finally:
            consumer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer
    console.print("[dim]bye.[/dim]")


async def _drive_run(
    session: Session,
    query: str,
    console: Console,
    ui: dict[str, Any],
    *,
    verbose: bool = False,
) -> None:
    """Stream events for one query through a TurnRenderer.

    Collapsed by default: retrieval folds to a one-line recap and the answer
    panel. With ``verbose`` each tool call streams above the prompt as it
    finishes. The renderer is stashed in ``ui["last"]`` so ``/expand`` can
    reprint the hidden detail. patch_stdout is active around this, so everything
    the renderer prints lands cleanly above the live prompt.
    """
    model_id = getattr(session.harness.adapter, "model", None)
    renderer = TurnRenderer(console, verbose=verbose, model_id=model_id)
    ui["last"] = renderer
    try:
        with renderer.live():
            async for event in session.run_stream(query):
                renderer.feed(event)
        renderer.finish()
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 — REPL must survive any harness error
        console.print(f"[red]✗ run failed:[/red] {e!r}")
