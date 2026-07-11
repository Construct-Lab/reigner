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
from rich.prompt import Prompt as RichPrompt
from rich.tree import Tree

from reigner.config import ReignerConfig

# Root names in `tools.fs.roots` must be segment-safe (same rule the config
# validator enforces): they become top-level directory names in the agent's
# virtual tree.
_ROOT_NAME_RE: Final = re.compile(r"[A-Za-z0-9_-]+")

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

# Blank-template paths a recipe wants omitted entirely. ``code_navigator`` is a
# sidecar over existing repos — it has no ingestion step, so the whole
# ingestion-shaped layout (schema, extractors, eval, library/, search-index/)
# would only be clutter. Keyed by recipe name; paths are project-relative and
# include the ``.gitkeep`` markers so their empty directories aren't realised.
_RECIPE_SKIP: Final[dict[str, set[str]]] = {
    "code_navigator": {
        "schema.yaml",
        "eval/cases.yaml",
        "extractors/__init__.py",
        "extractors/my_extractor.py",
        "extractors/pipeline.py",
        "library/artifacts/.gitkeep",
        "library/raw/.gitkeep",
        "search-index/.gitkeep",
    },
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
        if recipe == "code_navigator":
            # The one thing every user must set. Ask for it up front and write
            # it into the scaffolded reigner.yaml so the project is runnable —
            # but check writability first so we never waste the interaction.
            ensure_writable(target, force=force)
            _configure_navigator_roots(target, overrides)
        _scaffold(target, force=force, overrides=overrides, skip=_RECIPE_SKIP.get(recipe))
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
            rel_str = rel.as_posix()
            if rel.name == _KEEP_MARKER:
                # `.gitkeep` only exists to ship an empty directory. Realise the
                # directory — unless the recipe skipped this marker, in which
                # case the empty directory is unwanted too.
                if rel_str not in skip:
                    (target / rel.parent).mkdir(parents=True, exist_ok=True)
                continue
            template_paths.add(rel_str)
            if rel_str in skip:
                continue
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if rel_str in overrides:
                dest.write_text(_maybe_render(rel, overrides[rel_str], target.name))
            elif rel.name in _RENDER:
                dest.write_text(src.read_text().replace("{project_name}", target.name))
            else:
                shutil.copyfile(src, dest)

    # Overrides may *add* files the blank template doesn't ship — e.g. a recipe's
    # tuned reigner.yaml. Write any that the template loop above didn't cover.
    for rel_str, content in overrides.items():
        if rel_str in template_paths or rel_str in skip:
            continue
        dest = target / rel_str
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_maybe_render(Path(rel_str), content, target.name))

    # Generate the default reigner.yaml unless a recipe already supplied its own
    # tuned one via overrides. Single source of truth — the blank default is
    # never duplicated as a static template file.
    if "reigner.yaml" not in overrides:
        ReignerConfig.write_default(target / "reigner.yaml", name=target.name)


# ---------------------------------------------------------------------------
# Recipe scaffolds
# ---------------------------------------------------------------------------


def _configure_navigator_roots(target: Path, overrides: dict[str, str]) -> None:
    """Interactively collect repo roots and write them into the recipe yaml.

    Prompts for as many ``name → path`` pairs as the user wants (any names, any
    count) and injects them into the scaffolded ``reigner.yaml``. If the user
    enters none, the bundled placeholder roots are left in place so the file is
    still a valid, editable template.
    """
    console = Console()
    roots = _prompt_roots(console, target)
    if roots and "reigner.yaml" in overrides:
        overrides["reigner.yaml"] = _inject_roots(overrides["reigner.yaml"], roots)
    elif not roots:
        console.print(
            "[dim]No repos entered — left placeholder roots in reigner.yaml; "
            "edit them before `reigner chat`.[/dim]"
        )


def _prompt_roots(console: Console, target: Path) -> list[tuple[str, str]]:
    """Ask for ``name → path`` repo pairs until an empty name is entered."""
    console.print(
        "\n[bold]Repos to explore[/bold] — add one or more. "
        "Each name becomes a top-level directory the agent sees.\n"
        "[dim]Path can be relative (to this project), absolute, or ~/...[/dim]\n"
        "[dim]Press Enter on an empty name to finish.[/dim]"
    )
    roots: list[tuple[str, str]] = []
    seen: set[str] = set()
    while True:
        try:
            name = RichPrompt.ask("  Root name", default="", show_default=False).strip()
        except EOFError:
            break
        if not name:
            break
        if not _ROOT_NAME_RE.fullmatch(name):
            console.print(f"    [yellow]![/yellow] invalid name {name!r}; use [A-Za-z0-9_-]")
            continue
        if name in seen:
            console.print(f"    [yellow]![/yellow] {name!r} already added")
            continue
        try:
            path = RichPrompt.ask(f"  Path to {name!r}", default="", show_default=False).strip()
        except EOFError:
            break
        if not path:
            console.print("    [yellow]![/yellow] path can't be empty")
            continue
        _warn_if_not_dir(console, target, path)
        roots.append((name, path))
        seen.add(name)
    return roots


def _warn_if_not_dir(console: Console, target: Path, path: str) -> None:
    """Note (don't block) if a path doesn't resolve to a directory yet.

    Mirrors how the config resolves paths at runtime: ``~`` expands, absolute
    paths pass through, relative paths resolve against the project directory.
    Non-blocking — ``build_fs_tools`` enforces existence at ``chat`` startup.
    """
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = target / resolved
    if not resolved.resolve().is_dir():
        console.print(
            f"    [yellow]![/yellow] {path} isn't a directory yet — "
            "it must exist before `reigner chat`."
        )


def _inject_roots(yaml_text: str, roots: list[tuple[str, str]]) -> str:
    """Replace the ``roots:`` mapping in the recipe yaml with ``roots``.

    Rewrites only the ``roots:`` line and its indented entries; surrounding
    comments and keys (``write_enabled`` etc.) are preserved verbatim.
    """
    block = "    roots:\n" + "".join(f"      {name}: {path}\n" for name, path in roots)
    lines = yaml_text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    replaced = False
    while i < len(lines):
        if not replaced and lines[i].rstrip() == "    roots:":
            out.append(block)
            i += 1
            # Skip the old entries: 6-space-indented, non-comment mapping lines.
            while (
                i < len(lines)
                and lines[i].startswith("      ")
                and lines[i].strip()
                and not lines[i].lstrip().startswith("#")
            ):
                i += 1
            replaced = True
            continue
        out.append(lines[i])
        i += 1
    return "".join(out)


def _maybe_render(rel: Path, content: str, project_name: str) -> str:
    """Substitute ``{project_name}`` in files whose name is in ``_RENDER``.

    A recipe can ship a rendered file (e.g. ``README.md``); its ``{project_name}``
    placeholder should still be filled in with the target directory name, same
    as the blank template's copy.
    """
    if rel.name in _RENDER:
        return content.replace("{project_name}", project_name)
    return content


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

    # A recipe ships a working config, but the follow-up differs. An ingestion
    # recipe (has extractors/) needs a domain-specific prompt before `ingest`
    # can run; a sidecar recipe (no extractors/, e.g. code_navigator) just needs
    # its roots pointed at real repos before `chat`. Blank and guided stop at
    # `--help`.
    if mode.endswith("recipe"):
        if (target / "extractors").is_dir():
            last = (
                "  [dim]# edit extractors/my_extractor.py — write the extraction prompt[/dim]\n"
                "  [dim]# edit extractors/pipeline.py — name your entities[/dim]\n"
                "  reigner ingest\n"
                "  reigner chat"
            )
        else:
            last = (
                "  [dim]# edit reigner.yaml — point tools.fs.roots at your repos[/dim]\n"
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
