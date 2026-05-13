"""`reigner init` — scaffold a Reigner project.

Three modes per SPEC §14:

- ``--blank``   : empty stubs only (offline, fully working).
- ``--recipe``  : copy a recipe's bundled scaffolds (stubbed until T-32).
- ``--guided``  : interactive Q&A → LLM-generated REIGNER.md (stubbed).

Bare ``reigner init <name>`` errors out and lists the three modes; we
deliberately don't pick a default until ``--guided`` lands (the SPEC's
chosen default). This makes the in-progress state honest instead of
silently shipping a different default we'd have to flip back later.
"""

from __future__ import annotations

import re
import shutil
from importlib.resources import as_file, files
from pathlib import Path
from typing import Final

import typer
from rich.console import Console
from rich.tree import Tree

from reigner.config import ReignerConfig

NAME_RE: Final = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*$")

_STUB_RECIPE: Final = (
    "✗ Recipes are not yet bundled (tracked in T-32).\n"
    "  Use --blank for now:\n"
    "    reigner init {name} --blank"
)
_STUB_GUIDED: Final = (
    "✗ Guided init is not yet wired.\n  Use --blank for now:\n    reigner init {name} --blank"
)
_NO_MODE: Final = (
    "✗ Pick a mode for `reigner init`.\n\n"
    "  --blank     empty stubs only (offline)\n"
    "  --recipe    copy a recipe scaffold  (not yet — T-32)\n"
    "  --guided    interactive Q&A         (not yet)\n\n"
    "SPEC §14 makes --guided the default once it ships."
)

# Filenames within the blank template that should be rendered with substitutions.
# Everything else is copied byte-for-byte.
_RENDER: Final = {"README.md"}

# `.gitkeep` markers exist only to ship empty directories inside the wheel.
# They get stripped at scaffold time — the user's project shouldn't have them.
_KEEP_MARKER: Final = ".gitkeep"


def register(app: typer.Typer) -> None:
    app.command("init")(_init)


def _init(
    name: str = typer.Argument(..., help="Project name (also the target directory)."),
    blank: bool = typer.Option(False, "--blank", help="Empty stubs only (offline)."),
    recipe: str | None = typer.Option(
        None, "--recipe", metavar="NAME", help="Copy a recipe scaffold (not yet bundled)."
    ),
    guided: bool = typer.Option(False, "--guided", help="Interactive Q&A (not yet wired)."),
    force: bool = typer.Option(
        False, "--force", help="Overwrite scaffold files if the target is non-empty."
    ),
) -> None:
    """Scaffold a Reigner project at ``./<name>/``."""
    modes_picked = sum(bool(m) for m in (blank, recipe, guided))
    if modes_picked > 1:
        typer.echo("✗ pass at most one of --blank / --recipe / --guided", err=True)
        raise typer.Exit(2)

    if modes_picked == 0:
        typer.echo(_NO_MODE, err=True)
        raise typer.Exit(2)

    if not NAME_RE.match(name):
        typer.echo(
            f"✗ invalid project name {name!r}; must match [a-zA-Z_][a-zA-Z0-9_-]*",
            err=True,
        )
        raise typer.Exit(2)

    if recipe is not None:
        typer.echo(_STUB_RECIPE.format(name=name), err=True)
        raise typer.Exit(1)

    if guided:
        typer.echo(_STUB_GUIDED.format(name=name), err=True)
        raise typer.Exit(1)

    target = Path(name)
    _scaffold_blank(target, force=force)
    _print_success(target)


# ---------------------------------------------------------------------------
# Scaffold
# ---------------------------------------------------------------------------


def _scaffold_blank(target: Path, *, force: bool) -> None:
    if target.exists() and target.is_dir() and any(target.iterdir()) and not force:
        typer.echo(
            f"✗ ./{target} already exists and is non-empty.\n"
            f"  Pass --force to overwrite scaffold files in place\n"
            f"  (existing user files are not deleted, only overwritten by name).",
            err=True,
        )
        raise typer.Exit(1)

    target.mkdir(parents=True, exist_ok=True)

    template_root = files("reigner.cli.templates") / "blank"
    with as_file(template_root) as root:
        root_path = Path(root)
        for src in _walk(root_path):
            rel = src.relative_to(root_path)
            if rel.name == _KEEP_MARKER:
                # Realise the directory but skip the marker file itself.
                (target / rel.parent).mkdir(parents=True, exist_ok=True)
                continue
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if rel.name in _RENDER:
                rendered = src.read_text().replace("{project_name}", target.name)
                dest.write_text(rendered)
            else:
                shutil.copyfile(src, dest)

    # Single source of truth — never duplicated as a static template file.
    ReignerConfig.write_default(target / "reigner.yaml", name=target.name)


def _walk(root: Path) -> list[Path]:
    """Sorted list of every file under root. Sorted output → deterministic tests."""
    return sorted(p for p in root.rglob("*") if p.is_file())


# ---------------------------------------------------------------------------
# Success report
# ---------------------------------------------------------------------------


def _print_success(target: Path) -> None:
    console = Console()
    console.print(f"[green]✓[/green] Scaffolded [bold]{target}/[/bold] (blank mode)\n")

    tree = Tree(f"[bold]{target}/[/bold]")
    _build_tree(tree, target)
    console.print(tree)

    console.print(
        f"\n[dim]Next:[/dim]\n"
        f"  cd {target}\n"
        f"  cp .env.example .env   [dim]# add your API key[/dim]\n"
        f"  uv run reigner --help"
    )


def _build_tree(node: Tree, path: Path) -> None:
    for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name)):
        if child.is_dir():
            sub = node.add(f"[bold]{child.name}/[/bold]")
            _build_tree(sub, child)
        else:
            node.add(child.name)
