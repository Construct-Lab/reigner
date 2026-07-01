"""Per-turn terminal rendering for the chat REPL.

A :class:`TurnRenderer` sits between the harness event stream and the terminal.
It owns per-turn state — a call registry keyed by ``call_id`` and the collected
citations — and renders a turn in two phases:

- **Collapsed (default)** the retrieval phase folds to a single ``✓ Retrieved``
  recap line; only a ``Retrieving…`` header shows while it runs. This is mock B.
- **Verbose** (``--verbose`` / the REPL ``/verbose`` toggle) additionally streams
  one self-describing line per finished call (derived summary: hit / match
  counts, truncation) *above* the live prompt. This is mock C.

Either way the turn is capped with the recap, a numbered *Sources* block, and
the answer panel. Citations are always held back for the Sources block.

Why stream instead of an in-place ``rich.Live`` collapse: this REPL keeps a
prompt_toolkit prompt live at the bottom of the screen for type-ahead and
steering (see ``chat.py``). prompt_toolkit owns that bottom line; a ``rich.Live``
region fights it for the same cells, gluing the ``›`` caret onto the last live
frame. Streaming completed lines through the surrounding ``patch_stdout`` places
them cleanly above the prompt — the fallback the plan flagged for this exact
conflict. The loop and event protocol are untouched; ``summarise`` /
``clean_args`` (in ``_tool_summary``) do the untyped-result work.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from reigner.cli._tool_summary import clean_args, summarise
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
)

# Pseudo-tool that is represented in the Sources block, not the tool log.
_CITATION_TOOL = "register_citation"

_NAME_WIDTH = 18


@dataclass
class _Call:
    """One tool call and, once its result lands, its derived summary line."""

    name: str
    args: dict[str, Any]
    summary: str = ""
    done: bool = False
    truncated: bool = False
    cached: bool = False


class TurnRenderer:
    """Renders a single chat turn: streamed tool lines, then a committed cap.

    One instance per query. Wrap the feed loop in :meth:`live` (a no-op context
    manager kept for symmetry — there is no in-place region), feed it every
    event, then call :meth:`finish` to commit the recap / sources / answer.
    """

    def __init__(self, console: Console, *, verbose: bool = False) -> None:
        self._console = console
        self._verbose = verbose
        self._calls: dict[str, _Call] = {}
        self._order: list[str] = []  # call_ids in arrival order, citations excluded
        self._printed: set[str] = set()  # call_ids already streamed above the prompt
        self._citations: list[CitationEvent] = []
        self._final: FinalAnswerEvent | None = None
        self._header_shown = False
        self._started = time.monotonic()

    # -- lifecycle ---------------------------------------------------------

    @contextmanager
    def live(self) -> Iterator[TurnRenderer]:
        """No-op scope around the feed loop.

        There is deliberately no in-place ``rich.Live`` region — it would fight
        prompt_toolkit for the bottom line (see the module docstring). Kept as a
        context manager so callers read as "render this turn" and so a future
        live strategy can slot in without touching ``chat.py``.
        """
        yield self

    def feed(self, event: Event) -> None:
        """Fold one event into the turn's state, streaming finished tool lines."""
        if isinstance(event, ToolCallEvent):
            if event.name != _CITATION_TOOL:
                self._calls[event.call_id] = _Call(name=event.name, args=event.args)
                self._order.append(event.call_id)
                self._ensure_header()
        elif isinstance(event, ToolResultEvent):
            call = self._calls.get(event.call_id)
            if call is not None:  # else: orphan (e.g. a citation's own result)
                call.summary = summarise(call.name, event.result, truncated=event.truncated)
                call.truncated = event.truncated
                call.cached = event.cached
                call.done = True
                if self._verbose:  # collapsed mode folds detail into the recap
                    self._print_call(event.call_id)
        elif isinstance(event, CitationEvent):
            self._citations.append(event)
        elif isinstance(event, FinalAnswerEvent):
            self._final = event
        elif isinstance(event, StatusEvent):
            self._console.print(f"  [dim]· {event.message}[/dim]")
        elif isinstance(event, ClarificationEvent):
            self._console.print(
                Panel(event.question, title="clarification", border_style="yellow", expand=False)
            )
        elif isinstance(event, CompactionEvent):
            self._console.print(
                f"  [dim]~ compaction level={event.level} freed={event.tokens_freed} tokens[/dim]"
            )
        elif isinstance(event, OracleEscalationEvent):
            self._console.print(
                f"  [magenta]⇡ oracle[/magenta] {event.from_model} → {event.to_model} "
                f"([dim]{event.reason}[/dim])"
            )
        elif isinstance(event, SteeringAcceptedEvent):
            self._console.print(f"  [green]⇲ steering accepted[/green] mode={event.mode}")
        elif isinstance(event, ErrorEvent):
            tag = "[yellow]recoverable[/yellow]" if event.recoverable else "[red]error[/red]"
            self._console.print(f"  {tag} {event.error}")

    def finish(self) -> None:
        """Cap the turn with the retrieval recap, Sources block, and answer panel."""
        # In verbose mode, backfill any call that never got a result so the
        # streamed detail matches the recap count. Collapsed mode shows no
        # per-call lines — the recap stands in for them.
        if self._verbose:
            for call_id in self._order:
                if call_id not in self._printed:
                    self._print_call(call_id)

        blocks: list[RenderableType] = []
        if self._order:
            blocks.append(self._recap())
        if self._citations:
            blocks.append(self._sources_block())
        if self._final is not None:
            blocks.append(self._answer_panel(self._final))
        elif not self._order:
            # Nothing ran and no answer — stay silent rather than print an empty box.
            return
        for i, block in enumerate(blocks):
            if i:
                self._console.print()
            self._console.print(block)

    # -- streamed lines ----------------------------------------------------

    def _ensure_header(self) -> None:
        if not self._header_shown:
            self._console.print("  [bold magenta]Retrieving…[/bold magenta]")
            self._header_shown = True

    def print_detail(self) -> bool:
        """Reprint every tool line for this turn (the ``/expand`` action).

        Scrollback can't be folded in place, so ``/expand`` reprints the hidden
        per-call detail below the recap rather than un-collapsing it. Returns
        ``False`` when there was no retrieval to expand.
        """
        if not self._order:
            return False
        self._console.print("  [dim]expanded ↓[/dim]")
        for call_id in self._order:
            self._console.print(
                self._call_line(self._calls[call_id]), no_wrap=True, overflow="ellipsis"
            )
        return True

    def _print_call(self, call_id: str) -> None:
        if call_id in self._printed:
            return
        self._printed.add(call_id)
        # Keep each call on one physical line so the glyph/name columns stay
        # aligned; a too-long line clips with an ellipsis rather than wrapping.
        self._console.print(
            self._call_line(self._calls[call_id]), no_wrap=True, overflow="ellipsis"
        )

    def _call_line(self, call: _Call) -> Text:
        line = Text("     ")
        if not call.done:
            line.append("· ", style="dim")
        elif call.truncated:
            line.append("⚠ ", style="yellow")
        else:
            line.append("✓ ", style="green")
        line.append(call.name.ljust(_NAME_WIDTH), style="default")
        args_line = clean_args(call.args)
        if args_line:
            line.append(f"{args_line} ", style="dim")
        if not call.done:
            line.append("· no result", style="dim")
        elif call.summary:
            line.append("· ", style="dim")
            line.append(call.summary, style="bold yellow" if call.truncated else "yellow")
        return line

    # -- committed cap -----------------------------------------------------

    def _recap(self) -> Text:
        n = len(self._order)
        truncated = sum(1 for c in self._calls.values() if c.truncated)
        elapsed = time.monotonic() - self._started
        line = Text("  ")
        line.append("✓ ", style="green")
        line.append("Retrieved", style="bold green")
        meta = f"{n} call{'s' if n != 1 else ''}"
        if truncated:
            meta += f" · {truncated} truncated"
        tok = self._tokens()
        if tok is not None:
            meta += f" · {tok / 1000:.1f}k tok"
        meta += f" · {elapsed:.1f}s"
        line.append(f"  {meta}", style="dim")
        if not self._verbose:  # hint the hidden detail is one command away
            line.append("   /expand", style="dim")
        return line

    def _sources_block(self) -> Group:
        lines: list[Text] = [Text("  Sources", style="bold yellow")]
        for i, cite in enumerate(self._citations, start=1):
            line = Text("    ")
            line.append(f"[{i}] ", style="bold yellow")
            line.append(cite.source, style="default")
            loc = _render_locator(cite.locator)
            if loc:
                line.append(f"  {loc}", style="dim")
            lines.append(line)
        return Group(*lines)

    def _answer_panel(self, final: FinalAnswerEvent) -> Panel:
        return Panel(
            final.text or "[dim](no answer)[/dim]",
            title="Answer",
            title_align="left",
            border_style="magenta",
            padding=(1, 2),
        )

    # -- helpers -----------------------------------------------------------

    def _tokens(self) -> int | None:
        """Best-effort token count from the final answer's usage metadata, if any.

        No event carries a live context budget today, so this is only known once
        the answer lands. (Wiring a StatusEvent budget field is future scope.)
        """
        if self._final is None:
            return None
        usage = self._final.metadata.get("usage")
        if isinstance(usage, dict):
            total = usage.get("total")
            if isinstance(total, int) and total > 0:
                return total
        return None


def _render_locator(locator: dict[str, Any]) -> str:
    """Compact ``k=v`` rendering of a citation locator, keys sorted, empties dropped."""
    parts = [f"{k}={locator[k]}" for k in sorted(locator, key=str) if locator[k] not in (None, "")]
    return " · ".join(parts)


__all__ = ["TurnRenderer"]
