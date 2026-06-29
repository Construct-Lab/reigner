"""`reigner session` — manage durable sessions.

Seven subcommands wrapping the sessions backend:

- ``list``                       table of every session on disk (``--json``).
- ``show <id>``                  one session's rounds + citations (``--json``).
- ``tree <id>``                  the fork lineage containing ``<id>`` (``--json``).
- ``fork <id> [--at-turn N]``    branch a child at round N (no model call).
- ``replay <id> [--at-turn N] [--with-role PATH]``
                                 re-run round N live, optionally against a
                                 different ROLE (the only token-spending command).
- ``export <id> --to PATH``      copy the session JSONL (+ meta) to ``PATH``.
- ``import PATH``                read an exported JSONL back into the store.

Every ``<id>`` argument accepts an unambiguous prefix: ``a1b2`` resolves to
``a1b2c3d4…`` as long as exactly one session matches. Read commands touch only
the store on disk — no harness, no model. ``show`` is also reachable as
``reigner inspect session <id>`` (aliased there).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.tree import Tree as RichTree

from reigner.cli._env import load_project_env
from reigner.config import ReignerConfig
from reigner.harness.events import (
    CitationEvent,
    Event,
    FinalAnswerEvent,
    SchemaVersionMismatch,
    UserQueryEvent,
)
from reigner.sessions import (
    ReplayError,
    SessionNode,
    SessionStore,
    round_boundaries,
)
from reigner.sessions import (
    tree as session_tree,
)
from reigner.sessions.store import InvalidSessionId, SessionNotFound
from reigner.types import ConfigError

_DEFAULT_CONFIG = "reigner.yaml"

EXIT_OK = 0
EXIT_USAGE = 2

_QUEUED = "#b4541a"  # terracotta — the queried-node marker


def register(app: typer.Typer) -> None:
    """Register the ``session`` command group on the given Typer app."""
    sub = typer.Typer(
        name="session",
        help="Manage durable sessions: list, show, tree, fork, replay, export, import.",
        no_args_is_help=True,
    )
    sub.command("list")(_list)
    sub.command("show")(_show)
    sub.command("tree")(_tree)
    sub.command("fork")(_fork)
    sub.command("replay")(_replay)
    sub.command("export")(_export)
    sub.command("import")(_import)
    app.add_typer(sub)


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


def _load_config(config: str) -> ReignerConfig:
    config_path = Path(config)
    if not config_path.exists():
        _die(
            f"no {config_path} in {config_path.parent.resolve()} — "
            "run `reigner init <name> --blank` first",
            EXIT_USAGE,
        )
    try:
        return ReignerConfig.load(config_path)
    except ConfigError as e:
        _die(str(e), EXIT_USAGE)


def _store(config: str) -> SessionStore:
    cfg = _load_config(config)
    return SessionStore(cfg.resolve(cfg.sessions.store_path))


def _resolve_id(store: SessionStore, prefix: str) -> str:
    """Map a session-id prefix to exactly one full id, or exit with a usage error."""
    ids = [m.session_id for m in store.list()]
    if prefix in ids:  # an exact id wins, even if it also prefixes another
        return prefix
    matches = [sid for sid in ids if sid.startswith(prefix)]
    if not matches:
        _die(f"no session matching {prefix!r} in {store.root}", EXIT_USAGE)
    if len(matches) > 1:
        _die(f"{prefix!r} is ambiguous: {', '.join(sorted(matches))}", EXIT_USAGE)
    return matches[0]


def _round_count(store: SessionStore, session_id: str) -> int | None:
    """Number of conversational rounds (UserQueryEvents), or None if unreadable."""
    try:
        return sum(1 for ev in store.load_events(session_id) if isinstance(ev, UserQueryEvent))
    except (OSError, ValueError, SchemaVersionMismatch):
        return None


def _fmt_ts(ts: str) -> str:
    """ISO timestamp → ``YYYY-MM-DD HH:MM`` (best-effort; pass through on surprise)."""
    return ts.replace("T", " ")[:16] if "T" in ts else ts


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def _list(
    config: str = typer.Option(_DEFAULT_CONFIG, "--config", "-c"),
    json_output: bool = typer.Option(False, "--json", help="Emit the metas as JSON."),
) -> None:
    """List every session under the store, sorted by id."""
    store = _store(config)
    metas = store.list()

    if json_output:
        print(json.dumps([asdict(m) for m in metas], indent=2))
        return

    console = Console()
    if not metas:
        console.print(f"[dim]no sessions in {store.root}[/dim]")
        return

    from rich.table import Table

    table = Table(show_header=True, header_style="bold")
    table.add_column("id")
    table.add_column("title")
    table.add_column("rounds", justify="right")
    table.add_column("parent")
    table.add_column("updated")
    for m in metas:
        n = _round_count(store, m.session_id)
        table.add_row(
            m.session_id,
            m.title or "[dim]—[/dim]",
            str(n) if n is not None else "[dim]?[/dim]",
            m.parent_id or "[dim]—[/dim]",
            _fmt_ts(m.last_updated),
        )
    console.print(table)
    console.print(f"[dim]{len(metas)} session(s) · {store.root}[/dim]")


# ---------------------------------------------------------------------------
# show  (also: reigner inspect session <id>)
# ---------------------------------------------------------------------------


def _show(
    session_id: str = typer.Argument(..., metavar="ID", help="Session id (or unambiguous prefix)."),
    config: str = typer.Option(_DEFAULT_CONFIG, "--config", "-c"),
    json_output: bool = typer.Option(False, "--json", help="Emit the detail as JSON."),
) -> None:
    """Show one session: meta header plus each round's query, answer, and citations."""
    store = _store(config)
    sid = _resolve_id(store, session_id)
    meta = store.read_meta(sid)
    rounds = _rounds(list(store.load_events(sid)))

    if json_output:
        print(
            json.dumps(
                {
                    "session_id": sid,
                    "parent_id": meta.parent_id,
                    "title": meta.title,
                    "created": meta.created,
                    "last_updated": meta.last_updated,
                    "event_count": meta.event_count,
                    "rounds": rounds,
                },
                indent=2,
            )
        )
        return

    console = Console()
    title = f'  [dim]"{meta.title}"[/dim]' if meta.title else ""
    console.print(f"[bold]{sid}[/bold]{title}")
    console.print(
        f"[dim]parent: {meta.parent_id or '—'}   rounds: {len(rounds)}   "
        f"events: {meta.event_count}   updated: {_fmt_ts(meta.last_updated)}[/dim]"
    )
    for i, rnd in enumerate(rounds, 1):
        console.print(f"\nround {i} ▸ {rnd['query']}")
        if rnd["final_answer"] is not None:
            console.print(f"        ◂ {rnd['final_answer']}")
        else:
            console.print("        ◂ [dim](no final answer — clarification or error)[/dim]")
        for cite in rnd["citations"]:
            console.print(f"          [dim]· cite {cite}[/dim]")


def _rounds(events: list[Event]) -> list[dict[str, Any]]:
    """Group an event log into rounds by ``UserQueryEvent`` boundaries.

    Each round carries its query, the final answer (if the loop produced one),
    and the sources of any citations registered during it. Events before the
    first query (there shouldn't be any) are ignored.
    """
    rounds: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for ev in events:
        if isinstance(ev, UserQueryEvent):
            current = {"query": ev.query, "final_answer": None, "citations": []}
            rounds.append(current)
        elif current is None:
            continue
        elif isinstance(ev, FinalAnswerEvent):
            current["final_answer"] = ev.text
        elif isinstance(ev, CitationEvent):
            current["citations"].append(ev.source)
    return rounds


# ---------------------------------------------------------------------------
# tree
# ---------------------------------------------------------------------------


def _tree(
    session_id: str = typer.Argument(..., metavar="ID", help="Session id (or unambiguous prefix)."),
    config: str = typer.Option(_DEFAULT_CONFIG, "--config", "-c"),
    json_output: bool = typer.Option(False, "--json", help="Emit the nested tree as JSON."),
) -> None:
    """Show the fork lineage containing a session, with that node marked."""
    store = _store(config)
    sid = _resolve_id(store, session_id)
    root = session_tree(store, sid)

    if json_output:
        print(json.dumps(_node_json(root), indent=2))
        return

    console = Console()
    rich_tree = RichTree(_node_label(store, root))
    for child in root.children:
        _attach(store, rich_tree, child)
    console.print(rich_tree)


def _node_label(store: SessionStore, node: SessionNode) -> str:
    n = _round_count(store, node.session_id)
    rounds = f"{n} rounds" if n is not None else "?"
    title = f' "{node.meta.title}"' if node.meta.title else ""
    root = " · root" if node.meta.parent_id is None else ""
    marker = f"  [{_QUEUED}]← queried[/]" if node.marked else ""
    return f"[green]●[/green] {node.session_id}{title}  [dim]{rounds}{root}[/dim]{marker}"


def _attach(store: SessionStore, branch: RichTree, node: SessionNode) -> None:
    sub = branch.add(_node_label(store, node))
    for child in node.children:
        _attach(store, sub, child)


def _node_json(node: SessionNode) -> dict[str, Any]:
    return {
        "session_id": node.session_id,
        "title": node.meta.title,
        "parent_id": node.meta.parent_id,
        "marked": node.marked,
        "children": [_node_json(c) for c in node.children],
    }


# ---------------------------------------------------------------------------
# fork
# ---------------------------------------------------------------------------


def _fork(
    session_id: str = typer.Argument(..., metavar="ID", help="Session id (or unambiguous prefix)."),
    at_turn: int = typer.Option(
        -1, "--at-turn", metavar="N", help="Branch at round N (1-based); -1 = tail."
    ),
    config: str = typer.Option(_DEFAULT_CONFIG, "--config", "-c"),
) -> None:
    """Branch a new child session at round N. Does not call the model."""
    from reigner.harness.agent import Session

    harness = _build_harness(config)
    sid = _resolve_id(harness.store, session_id)
    try:
        child = Session.load(sid, harness=harness).fork(at_turn=at_turn)
    except (SessionNotFound, ReplayError, ValueError) as e:
        _die(str(e), EXIT_USAGE)
    typer.echo(f"✓ forked {sid} @ round {at_turn} → {child.id}")


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------


def _replay(
    session_id: str = typer.Argument(..., metavar="ID", help="Session id (or unambiguous prefix)."),
    at_turn: int = typer.Option(
        -1, "--at-turn", metavar="N", help="Replay round N (1-based); -1 = last round."
    ),
    with_role: str | None = typer.Option(
        None,
        "--with-role",
        metavar="PATH",
        help="Re-run against this ROLE file instead of the config's.",
    ),
    config: str = typer.Option(_DEFAULT_CONFIG, "--config", "-c"),
) -> None:
    """Re-run a recorded round live against the current (or overridden) ROLE.

    Forks at round N, re-issues that round's recorded query, and runs it to
    completion on the child — leaving the original untouched and diff-able. The
    only session command that spends tokens.
    """
    from reigner.harness.agent import Session

    load_project_env(Path(config))
    harness = _build_harness(config, role_file=with_role)
    sid = _resolve_id(harness.store, session_id)

    parent = Session.load(sid, harness=harness)
    n = len(round_boundaries(parent.events()))
    turn = n if at_turn == -1 else at_turn
    if n == 0:
        _die(f"session {sid} has no recorded rounds to replay", EXIT_USAGE)
    if turn < 1 or turn > n:
        _die(f"--at-turn {at_turn} out of range — session has {n} round(s)", EXIT_USAGE)

    try:
        child = asyncio.run(parent.replay(turn))
    except (ReplayError, ValueError) as e:
        _die(str(e), EXIT_USAGE)
    typer.echo(f"✓ replayed round {turn} of {sid} → {child.id}")


# ---------------------------------------------------------------------------
# export / import
# ---------------------------------------------------------------------------


def _export(
    session_id: str = typer.Argument(..., metavar="ID", help="Session id (or unambiguous prefix)."),
    to: str = typer.Option(..., "--to", metavar="PATH", help="Destination .jsonl path."),
    config: str = typer.Option(_DEFAULT_CONFIG, "--config", "-c"),
) -> None:
    """Copy a session's JSONL (plus its meta sidecar) to a portable file."""
    store = _store(config)
    sid = _resolve_id(store, session_id)
    try:
        dest = store.export(sid, to)
    except (SessionNotFound, OSError) as e:
        _die(str(e), EXIT_USAGE)
    typer.echo(f"✓ exported {sid} → {dest}")


def _import(
    src: str = typer.Argument(..., metavar="PATH", help="Path to an exported session .jsonl."),
    config: str = typer.Option(_DEFAULT_CONFIG, "--config", "-c"),
) -> None:
    """Read an exported session JSONL back into the store."""
    store = _store(config)
    try:
        sid = store.import_(src)
    except (FileNotFoundError, FileExistsError, InvalidSessionId, ValueError) as e:
        _die(str(e), EXIT_USAGE)
    typer.echo(f"✓ imported → {sid}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_harness(config: str, *, role_file: str | None = None) -> Any:
    """Build a Harness from the config, surfacing config errors as usage errors."""
    from reigner.harness.agent import Harness

    config_path = Path(config)
    if not config_path.exists():
        _die(
            f"no {config_path} in {config_path.parent.resolve()} — "
            "run `reigner init <name> --blank` first",
            EXIT_USAGE,
        )
    try:
        return Harness.from_config(config_path, role_file=role_file)
    except ConfigError as e:
        _die(str(e), EXIT_USAGE)


def _die(msg: str, code: int) -> NoReturn:
    typer.echo(f"✗ {msg}", err=True)
    raise typer.Exit(code)
