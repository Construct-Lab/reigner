"""`reigner init` — scaffold a Reigner project.

Three modes:

- ``--guided``  : interactive Q&A → model-generated REIGNER.md + schema.yaml.
  This is the default — bare ``reigner init <name>`` runs it.
- ``--recipe``  : copy a recipe's bundled scaffolds (not yet bundled).
- ``--blank``   : empty stubs only (offline, fully working).

The guided flow lives in :mod:`reigner.cli._guided`; it reuses the scaffolder
here for everything except the two files it generates (``REIGNER.md`` and
``schema.yaml``) and the gated extractor stub.
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
    "✗ Recipes are not yet bundled.\n  Use --blank for now:\n    reigner init {name} --blank"
)

# Filenames within the blank template that should be rendered with substitutions.
# Everything else is copied byte-for-byte.
_RENDER: Final = {"README.md"}

# `.gitkeep` markers exist only to ship empty directories inside the wheel.
# They get stripped at scaffold time — the user's project shouldn't have them.
_KEEP_MARKER: Final = ".gitkeep"


def register(app: typer.Typer) -> None:
    """Register the ``init`` command on the given Typer app."""
    app.command("init")(_init)


def _init(
    name: str = typer.Argument(..., help="Project name (also the target directory)."),
    blank: bool = typer.Option(False, "--blank", help="Empty stubs only (offline)."),
    recipe: str | None = typer.Option(
        None, "--recipe", metavar="NAME", help="Copy a recipe scaffold (not yet bundled)."
    ),
    guided: bool = typer.Option(
        False, "--guided", help="Interactive Q&A → model-generated files (the default)."
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite scaffold files if the target is non-empty."
    ),
) -> None:
    """Scaffold a Reigner project at ``./<name>/``."""
    modes_picked = sum(bool(m) for m in (blank, recipe, guided))
    if modes_picked > 1:
        typer.echo("✗ pass at most one of --blank / --recipe / --guided", err=True)
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

    if blank:
        target = Path(name)
        _scaffold(target, force=force)
        _print_success(target)
        return

    # Guided is the default: it runs for an explicit --guided and for
    # bare `reigner init <name>`. Imported lazily so blank/recipe paths don't
    # pay for the model-adapter import surface.
    from reigner.cli._guided import run_guided

    run_guided(name, force=force)


# ---------------------------------------------------------------------------
# Scaffold
# ---------------------------------------------------------------------------


def ensure_writable(target: Path, *, force: bool) -> None:
    """Refuse to scaffold into a non-empty directory unless ``--force``.

    Exposed (no underscore) so the guided flow can fail this check *before*
    the interactive Q&A and model calls, rather than wasting them.
    """
    if target.exists() and target.is_dir() and any(target.iterdir()) and not force:
        typer.echo(
            f"✗ ./{target} already exists and is non-empty.\n"
            f"  Pass --force to overwrite scaffold files in place\n"
            f"  (existing user files are not deleted, only overwritten by name).",
            err=True,
        )
        raise typer.Exit(1)


def _scaffold(
    target: Path,
    *,
    force: bool,
    overrides: dict[str, str] | None = None,
    skip: set[str] | None = None,
) -> None:
    """Materialise the blank template into ``target``.

    ``overrides`` maps a project-relative path to file content that replaces
    the template's version (guided uses it for ``REIGNER.md`` / ``schema.yaml``).
    ``skip`` is a set of project-relative paths to omit entirely (guided uses
    it to drop the extractor stub when the confirmation gate is declined).
    """
    overrides = overrides or {}
    skip = skip or set()

    ensure_writable(target, force=force)
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
            rel_str = rel.as_posix()
            if rel_str in skip:
                continue
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if rel_str in overrides:
                dest.write_text(overrides[rel_str])
            elif rel.name in _RENDER:
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


def _print_success(target: Path, *, mode: str = "blank") -> None:
    console = Console()
    console.print(f"[green]✓[/green] Scaffolded [bold]{target}/[/bold] ({mode} mode)\n")

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
