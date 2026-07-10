"""`reigner init` — scaffold a Reigner project.

Three modes:

- ``--guided``  : interactive Q&A → model-generated REIGNER.md + schema.yaml.
  This is the default — bare ``reigner init <name>`` runs it.
- ``--recipe``  : copy a bundled recipe's curated files over the shared layout.
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

# Recipes are bundled under this package, one directory per recipe.
_RECIPES_PKG: Final = "reigner.recipes"

# Recipe files whose destination path differs from their name in the bundle.
# The extractor + pipeline live at the package root in the bundle (so their
# intra-package import resolves and type-checks); they land under extractors/.
_RECIPE_RENAME: Final = {
    "my_extractor.py": "extractors/my_extractor.py",
    "pipeline.py": "extractors/pipeline.py",
}

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
        None, "--recipe", metavar="NAME", help="Copy a bundled recipe (e.g. document_qa)."
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
        target = Path(name)
        overrides = _recipe_overrides(recipe)
        _scaffold(target, force=force, overrides=overrides)
        _print_success(target, mode=f"{recipe} recipe")
        return

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

    template_paths: set[str] = set()
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
            template_paths.add(rel_str)
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

    # Overrides may *add* files the blank template doesn't ship — e.g. a recipe's
    # tuned reigner.yaml. Write any that the template loop above didn't cover.
    for rel_str, content in overrides.items():
        if rel_str in template_paths or rel_str in skip:
            continue
        dest = target / rel_str
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)

    # Generate the default reigner.yaml unless a recipe already supplied its own
    # tuned one via overrides. Single source of truth — the blank default is
    # never duplicated as a static template file.
    if "reigner.yaml" not in overrides:
        ReignerConfig.write_default(target / "reigner.yaml", name=target.name)


# ---------------------------------------------------------------------------
# Recipe scaffolds
# ---------------------------------------------------------------------------


def _recipe_overrides(recipe: str) -> dict[str, str]:
    """Read a bundled recipe into a ``{project-relative path: content}`` map.

    Files are copied verbatim onto the shared blank layout; the extractor and
    pipeline land under ``extractors/``. The recipe's own ``reigner.yaml`` is
    included, so :func:`_scaffold` skips generating the blank default. Unknown
    recipe names fail loudly with the list of what is bundled.
    """
    recipe_root = files(_RECIPES_PKG) / recipe
    if not recipe_root.is_dir():
        available = _available_recipes()
        hint = f" Available: {', '.join(available)}." if available else ""
        typer.echo(f"✗ unknown recipe {recipe!r}.{hint}", err=True)
        raise typer.Exit(2)

    overrides: dict[str, str] = {}
    with as_file(recipe_root) as root:
        root_path = Path(root)
        for src in _walk(root_path):
            rel = src.relative_to(root_path).as_posix()
            if rel == "__init__.py":
                continue
            overrides[_RECIPE_RENAME.get(rel, rel)] = src.read_text()
    return overrides


def _available_recipes() -> list[str]:
    """Names of bundled recipes — every ``reigner/recipes/<name>/`` package."""
    root = files(_RECIPES_PKG)
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "reigner.yaml").is_file())


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

    # A recipe ships a working config, but extraction is domain-specific: the
    # user writes the prompt / entity naming before `ingest` can run. Blank and
    # guided stop at `--help`.
    if mode.endswith("recipe"):
        last = (
            "  [dim]# edit extractors/my_extractor.py — write the extraction prompt[/dim]\n"
            "  [dim]# edit extractors/pipeline.py — name your entities[/dim]\n"
            "  reigner ingest\n"
            "  reigner chat"
        )
    else:
        last = "  reigner --help"
    console.print(
        f"\n[dim]Next:[/dim]\n"
        f"  cd {target}\n"
        f"  cp .env.example .env   [dim]# add your API key[/dim]\n"
        f"{last}"
    )


def _build_tree(node: Tree, path: Path) -> None:
    for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name)):
        if child.is_dir():
            sub = node.add(f"[bold]{child.name}/[/bold]")
            _build_tree(sub, child)
        else:
            node.add(child.name)
