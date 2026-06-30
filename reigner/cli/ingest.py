"""`reigner ingest` — run a user's IngestionPipeline over raw documents.

Convention default: bare ``reigner ingest`` resolves
``extractors.pipeline:pipeline`` against the project root (CWD) and walks
``library/raw/``. The scaffolded ``extractors/pipeline.py`` stub is the
landing pad — the user uncomments and fills in. Pass ``--pipeline`` to
point elsewhere; with ``--pipeline`` you must also pass ``--source`` (no
per-pipeline default lookup, no guessing).

Output mirrors ``reigner chat``: rich-formatted progress lines by default,
NDJSON event stream with ``--json``. Exit codes: 0 ok, 1 runtime (one or
more sources failed), 2 usage.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from typing import Literal, NoReturn

import typer
from rich.console import Console

from reigner.cli._env import load_project_env
from reigner.harness.events import ErrorEvent, StatusEvent, to_json
from reigner.ingestion import IngestionPipeline

_DEFAULT_PIPELINE = "extractors.pipeline:pipeline"
_DEFAULT_SOURCE = "library/raw"

# Exit codes — match cli/chat.py.
EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2

OnError = Literal["raise", "dead_letter", "skip"]


def register(app: typer.Typer) -> None:
    """Register the ``ingest`` command on the given Typer app."""
    app.command("ingest")(_ingest)


def _ingest(
    pipeline_spec: str | None = typer.Option(
        None,
        "--pipeline",
        metavar="MODULE:OBJ",
        help=(
            "Dotted path to an IngestionPipeline (e.g. extractors.pipeline:pipeline). "
            f"Defaults to {_DEFAULT_PIPELINE!r} when omitted."
        ),
    ),
    source: str | None = typer.Option(
        None,
        "--source",
        metavar="PATH",
        help=(
            f"Directory or file of raw documents. Defaults to {_DEFAULT_SOURCE!r} "
            "only when --pipeline is also omitted; explicit --pipeline requires explicit --source."
        ),
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit one event per line as NDJSON instead of rich progress."
    ),
    on_error: str | None = typer.Option(
        None,
        "--on-error",
        metavar="POLICY",
        help="Override pipeline's on_error policy: raise | skip | dead_letter.",
    ),
    concurrency: int | None = typer.Option(
        None, "--concurrency", metavar="N", help="Override pipeline's worker semaphore."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Discover sources, print the plan (file → loader), exit without writes.",
    ),
) -> None:
    """Run an IngestionPipeline over a directory of raw documents."""
    # Source-required-with-pipeline rule. The convention default only applies
    # when *both* are unset — any explicit --pipeline forces an explicit --source.
    if pipeline_spec is not None and source is None:
        _die("--source is required when --pipeline is passed", EXIT_USAGE)

    resolved_spec = pipeline_spec or _DEFAULT_PIPELINE
    resolved_source = Path(source or _DEFAULT_SOURCE)

    load_project_env()
    pipeline = _resolve_pipeline(resolved_spec)
    _apply_overrides(pipeline, on_error=on_error, concurrency=concurrency)

    if dry_run:
        code = _do_dry_run(pipeline, resolved_source)
        raise typer.Exit(code)

    code = asyncio.run(_run(pipeline, resolved_source, json_mode=json_output))
    raise typer.Exit(code)


# ---------------------------------------------------------------------------
# Pipeline resolution
# ---------------------------------------------------------------------------


def _resolve_pipeline(spec: str) -> IngestionPipeline:
    """Resolve 'module:obj' → IngestionPipeline with friendly errors."""
    if ":" not in spec:
        _die(
            f"--pipeline must be 'module:object', got {spec!r}\n"
            "  hint: extractors.pipeline:pipeline",
            EXIT_USAGE,
        )
    mod_path, _, attr = spec.partition(":")
    if not mod_path or not attr:
        _die(f"--pipeline must have both module and object: got {spec!r}", EXIT_USAGE)

    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    try:
        mod = importlib.import_module(mod_path)
    except ImportError as e:
        _die(
            f"could not import {mod_path!r}: {e}\n"
            "  hint: run from project root; ensure __init__.py exists",
            EXIT_USAGE,
        )

    if not hasattr(mod, attr):
        public = sorted(n for n in dir(mod) if not n.startswith("_"))
        avail = ", ".join(public) if public else "(none)"
        _die(
            f"{mod_path!r} has no attribute {attr!r}. available: {avail}",
            EXIT_USAGE,
        )

    obj = getattr(mod, attr)
    if not isinstance(obj, IngestionPipeline):
        _die(
            f"{spec} is {type(obj).__name__}, expected IngestionPipeline",
            EXIT_USAGE,
        )
    return obj


def _apply_overrides(
    pipeline: IngestionPipeline,
    *,
    on_error: str | None,
    concurrency: int | None,
) -> None:
    """CLI flag overrides mutate the pipeline's private attrs in place.

    The pipeline doesn't expose a public setter and we don't have the original
    constructor kwargs (the user built the instance). Mutating is the pragmatic
    path; the alternative is making the user rebuild the pipeline per invocation.
    """
    if on_error is not None:
        if on_error not in ("raise", "skip", "dead_letter"):
            _die(
                f"--on-error must be one of raise|skip|dead_letter, got {on_error!r}",
                EXIT_USAGE,
            )
        # dead_letter without a configured path on the pipeline would explode at
        # runtime; the pipeline's own constructor rejects it, but here we only
        # accept the override if the path was already set.
        if on_error == "dead_letter" and pipeline._dead_letter_path is None:  # noqa: SLF001
            _die(
                "--on-error dead_letter requires the pipeline to have dead_letter_path set "
                "in its constructor",
                EXIT_USAGE,
            )
        pipeline._on_error = on_error  # type: ignore[assignment]  # noqa: SLF001

    if concurrency is not None:
        if concurrency < 1:
            _die(f"--concurrency must be >= 1, got {concurrency}", EXIT_USAGE)
        pipeline._concurrency = concurrency  # noqa: SLF001


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------


async def _run(pipeline: IngestionPipeline, source: Path, *, json_mode: bool) -> int:
    """Drain run_stream, render events, print report. Returns exit code."""
    console = Console()

    if not json_mode:
        console.print(f"[dim]→ pipeline: {type(pipeline).__name__}[/dim]")
        console.print(
            f"[dim]→ source: {source}  · concurrency {pipeline._concurrency}  "  # noqa: SLF001
            f"· on_error={pipeline._on_error}[/dim]"  # noqa: SLF001
        )

    try:
        async for evt in pipeline.run_stream(source):
            if json_mode:
                print(to_json(evt), flush=True)
                continue
            if isinstance(evt, StatusEvent):
                console.print(f"[green]●[/green] {evt.message}")
            elif isinstance(evt, ErrorEvent):
                console.print(f"[red]✗[/red] {evt.error}")
    except FileNotFoundError as e:
        _die(str(e), EXIT_USAGE)
    except Exception as e:
        if json_mode:
            # Surface as a final NDJSON line so scripts can detect failure.
            print(f'{{"type":"fatal","error":{_json_str(repr(e))}}}', flush=True)
        else:
            console.print(f"[red]✗ fatal:[/red] {e}")
        return EXIT_RUNTIME

    report = pipeline.last_report
    if report is None:
        return EXIT_RUNTIME

    if not json_mode:
        _print_report(console, report)

    return EXIT_RUNTIME if report.failed else EXIT_OK


def _print_report(console: Console, report: object) -> None:
    """Render the final IngestionReport summary line."""
    # Attribute access kept generic so the renderer doesn't import the dataclass
    # name in the module signature.
    succeeded = getattr(report, "succeeded", 0)
    failed = getattr(report, "failed", 0)
    skipped = getattr(report, "skipped", 0)
    tokens = getattr(report, "total_tokens", 0)
    cost = getattr(report, "total_cost_usd", 0.0)
    seconds = getattr(report, "wall_clock_seconds", 0.0)

    console.print("[dim]" + "─" * 40 + "[/dim]")
    status = "ok" if failed == 0 else "with failures"
    console.print(
        f"ingestion complete ({status}): "
        f"[green]{succeeded} ok[/green], "
        f"[red]{failed} failed[/red], "
        f"[yellow]{skipped} skipped[/yellow]"
    )
    console.print(f"[dim]wall clock: {seconds:.1f}s · {tokens} tokens · ${cost:.3f}[/dim]")


def _do_dry_run(pipeline: IngestionPipeline, source: Path) -> int:
    """Discover sources, print loader assignment, exit without running."""
    console = Console()
    try:
        sources = pipeline._discover(source)  # noqa: SLF001
    except FileNotFoundError as e:
        _die(str(e), EXIT_USAGE)
    except NotADirectoryError as e:
        _die(str(e), EXIT_USAGE)

    console.print(f"[dim]dry run · source: {source}[/dim]")
    if not sources:
        console.print("[yellow]no matching sources found[/yellow]")
        return EXIT_OK

    ext_map = pipeline._ext_to_loader  # noqa: SLF001
    console.print(f"would ingest [green]{len(sources)}[/green] source(s):")
    for src in sources:
        loader = ext_map.get(src.suffix.lower())
        loader_name = type(loader).__name__ if loader is not None else "?"
        console.print(f"  [dim]{src}[/dim] → [cyan]{loader_name}[/cyan]")
    return EXIT_OK


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _die(msg: str, code: int) -> NoReturn:
    typer.echo(f"✗ {msg}", err=True)
    raise typer.Exit(code)


def _json_str(s: str) -> str:
    """Minimal JSON-string-escape for the fatal-error fallback line."""
    import json

    return json.dumps(s)
