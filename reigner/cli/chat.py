"""`reigner chat` — interactive REPL and headless one-shot modes.

Three modes from one Typer command:

- ``reigner chat``                       interactive REPL with steering.
- ``reigner chat --print "<q>"``         one-shot; stdout = final answer text.
- ``reigner chat --print "<q>" --json``  one-shot; ND-JSON of every event.

The REPL streams the harness event protocol (SPEC §5.2). The prompt stays live
while a run is in flight, giving two distinct mid-run actions:

- **Enter** queues the typed text as the *next question* — the current run
  answers on its own, then the queued question runs as a fresh turn (type-ahead,
  like queuing a follow-up in Claude Code / ChatGPT).
- **Alt+Enter** (or **Esc then Enter**, which needs no Option-as-Meta) *steers*
  the in-flight run (SPEC §5.6): the text folds into the current loop as a user
  turn at its next boundary, bending this answer rather than starting a new one.

Idle Enter submits a fresh query. There is intentionally no mid-turn preemption
— neither action aborts the in-flight model call (see issue #48).
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path
from typing import Any

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.panel import Panel

from reigner.cli._env import load_project_env
from reigner.harness.agent import Harness, Session
from reigner.harness.events import (
    CitationEvent,
    ClarificationEvent,
    CompactionEvent,
    ErrorEvent,
    Event,
    FinalAnswerEvent,
    OracleEscalationEvent,
    StatusEvent,
    SteeringAcceptedEvent,
    ToolCallEvent,
    ToolResultEvent,
    to_json,
)
from reigner.types import ConfigError

_DEFAULT_CONFIG = "reigner.yaml"

# Exit codes (SPEC §17 is informal; we pick conventional values):
#   0 — final answer produced
#   1 — runtime error (loop error event, no final answer)
#   2 — usage error (missing config, clarification in --print mode)
EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2


def register(app: typer.Typer) -> None:
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
) -> None:
    """Interactive chat REPL, or a one-shot run with ``--print``."""
    if json_output and print_query is None:
        typer.echo("✗ --json only makes sense with --print", err=True)
        raise typer.Exit(EXIT_USAGE)

    session = _build_session(Path(config))

    if print_query is not None:
        code = asyncio.run(_run_print(session, print_query, json_output=json_output))
        raise typer.Exit(code)

    asyncio.run(_run_repl(session))


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


async def _run_repl(session: Session) -> None:
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

    prompt: PromptSession[str] = PromptSession(message="› ", key_bindings=kb)

    console.print(
        "[dim]reigner chat — Enter submits (mid-run: queues your next "
        "question); Alt+Enter / Esc-then-Enter steers the running answer; "
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
            run_task = asyncio.ensure_future(_drive_run(session, query, console))
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
            await prompt.prompt_async()
        except (EOFError, KeyboardInterrupt):
            pass
        finally:
            consumer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer
    console.print("[dim]bye.[/dim]")


async def _drive_run(session: Session, query: str, console: Console) -> None:
    """Stream events for one query and render each as a compact line / panel."""
    try:
        async for event in session.run_stream(query):
            _render_event(event, console)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 — REPL must survive any harness error
        # patch_stdout is active while this runs, so a plain print renders
        # cleanly above the live prompt.
        console.print(f"[red]✗ run failed:[/red] {e!r}")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_event(event: Event, console: Console) -> None:
    """One compact line per intermediate event; final answer in a Panel."""
    if isinstance(event, StatusEvent):
        console.print(f"  [dim]·[/dim] status: {event.message}")
    elif isinstance(event, ToolCallEvent):
        args_repr = _short_args(event.args)
        console.print(f"  [dim]→[/dim] tool_call  [bold]{event.name}[/bold]({args_repr})")
    elif isinstance(event, ToolResultEvent):
        trunc = " [yellow]truncated[/yellow]" if event.truncated else ""
        cached = " [cyan]cached[/cyan]" if event.cached else ""
        console.print(f"  [dim]←[/dim] tool_result{trunc}{cached}")
    elif isinstance(event, CitationEvent):
        console.print(f"  [dim][cite][/dim] {event.source}")
    elif isinstance(event, ClarificationEvent):
        console.print(
            Panel(event.question, title="clarification", border_style="yellow", expand=False)
        )
    elif isinstance(event, CompactionEvent):
        console.print(
            f"  [dim]~[/dim] compaction level={event.level} freed={event.tokens_freed} tokens"
        )
    elif isinstance(event, OracleEscalationEvent):
        console.print(
            f"  [magenta]⇡ oracle[/magenta] {event.from_model} → {event.to_model} "
            f"([dim]{event.reason}[/dim])"
        )
    elif isinstance(event, SteeringAcceptedEvent):
        console.print(f"  [green]⇲ steering accepted[/green] mode={event.mode}")
    elif isinstance(event, ErrorEvent):
        tag = "[yellow]recoverable[/yellow]" if event.recoverable else "[red]error[/red]"
        console.print(f"  {tag} {event.error}")
    elif isinstance(event, FinalAnswerEvent):
        console.print(Panel(event.text, title="final answer", border_style="green"))


def _short_args(args: dict[str, Any], *, max_len: int = 80) -> str:
    parts = []
    for k, v in args.items():
        rendered = repr(v)
        if len(rendered) > 30:
            rendered = rendered[:27] + "..."
        parts.append(f"{k}={rendered}")
    joined = ", ".join(parts)
    if len(joined) > max_len:
        joined = joined[: max_len - 3] + "..."
    return joined
