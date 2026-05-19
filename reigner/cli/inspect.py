"""`reigner inspect` — introspect what the harness sees (T-20).

Four subcommands today: ``artifacts``, ``role``, ``tools``, ``config``.
Deferred: ``index`` (T-10 BM25), ``session`` (T-21 owns ``reigner session``).

Each subcommand loads ``reigner.yaml`` (default ``./reigner.yaml``; override
with ``--config / -c``) via :meth:`ReignerConfig.load`. ``inspect role`` and
``inspect tools`` deliberately stop short of full composition — the composed
ROLE (REIGNER.md + active skill blocks + dynamic context) needs the skills
loader (T-31); ``inspect tools`` enumerates the registry as wired from this
config, not a live ``ArtifactStore`` / ``SearchIndex`` (those depend on T-09
/ T-10). Each output makes the deferral visible to users.
"""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from reigner.artifacts import ArtifactSchema
from reigner.config import ReignerConfig
from reigner.tools.base import ToolSpec
from reigner.types import ConfigError

_DEFAULT_CONFIG = "reigner.yaml"

EXIT_OK = 0
EXIT_USAGE = 2


def register(app: typer.Typer) -> None:
    sub = typer.Typer(
        name="inspect",
        help="Introspect role, artifacts, tools, and resolved config.",
        no_args_is_help=True,
    )
    sub.command("artifacts")(_inspect_artifacts)
    sub.command("role")(_inspect_role)
    sub.command("tools")(_inspect_tools)
    sub.command("config")(_inspect_config)
    app.add_typer(sub)


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


def _load_config(config_path: Path) -> ReignerConfig:
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


# ---------------------------------------------------------------------------
# artifacts
# ---------------------------------------------------------------------------


def _inspect_artifacts(
    config: str = typer.Option(_DEFAULT_CONFIG, "--config", "-c"),
    entity: str | None = typer.Option(
        None, "--entity", metavar="ID", help="Drill into a single entity (e.g. AAPL/2024)."
    ),
) -> None:
    """Walk the configured artifact store and render a tree of entities."""
    cfg = _load_config(Path(config))
    console = Console()

    if cfg.tools.artifacts is None:
        _die(
            "tools.artifacts is not configured in reigner.yaml — nothing to inspect.\n"
            "  hint: add tools.artifacts.root and tools.artifacts.schema",
            EXIT_USAGE,
        )

    root = cfg.resolve(cfg.tools.artifacts.root)
    schema_path = cfg.resolve(cfg.tools.artifacts.schema_path)

    if not root.exists():
        console.print(f"[yellow]artifacts root does not exist yet: {root}[/yellow]")
        console.print("[dim]run `reigner ingest` to populate it.[/dim]")
        return

    try:
        schema = ArtifactSchema.from_yaml(schema_path)
    except (OSError, ValueError) as e:
        _die(f"cannot load schema {schema_path}: {e}", EXIT_USAGE)

    if entity is not None:
        _render_entity_detail(console, root, schema, entity)
        return

    _render_artifacts_tree(console, root, schema)


def _render_artifacts_tree(console: Console, root: Path, schema: ArtifactSchema) -> None:
    """Tree view: one node per entity directory, sized by `entity_path` depth."""
    placeholders = schema.entity_path_keys()
    depth = len(placeholders)
    shape = "/".join("{" + p + "}" for p in placeholders)
    tree = Tree(f"[bold]{root}[/bold]  [dim]({shape})[/dim]")

    entities = sorted(_walk_entities(root, depth))
    if not entities:
        tree.add("[dim](no entities yet)[/dim]")
        console.print(tree)
        return

    # Group by first placeholder for a readable two-level rendering when depth>=2.
    if depth >= 2:
        grouped: dict[str, list[Path]] = {}
        for ent in entities:
            top = ent.parts[-depth]
            grouped.setdefault(top, []).append(ent)
        for top, members in grouped.items():
            top_node = tree.add(f"{top}/  [dim]({len(members)})[/dim]")
            for member in members:
                rel = "/".join(member.parts[-depth + 1 :])
                top_node.add(f"{rel}")
    else:
        for ent in entities:
            tree.add(ent.name)

    console.print(tree)
    console.print(f"\n[dim]{len(entities)} entities · root: {root}[/dim]")


def _walk_entities(root: Path, depth: int) -> list[Path]:
    """Return directories at exactly `depth` below `root` (one per entity)."""
    out: list[Path] = []

    def _recurse(p: Path, remaining: int) -> None:
        if remaining == 0:
            out.append(p)
            return
        if not p.is_dir():
            return
        for child in sorted(p.iterdir()):
            if child.is_dir():
                _recurse(child, remaining - 1)

    _recurse(root, depth)
    return out


def _render_entity_detail(
    console: Console, root: Path, schema: ArtifactSchema, entity: str
) -> None:
    """List one entity's sections + json artifacts + sizes."""
    entity_dir = root / entity
    if not entity_dir.exists() or not entity_dir.is_dir():
        _die(f"entity not found: {entity_dir}", EXIT_USAGE)

    tree = Tree(f"[bold]{entity}/[/bold]  [dim]({entity_dir})[/dim]")
    for path in sorted(entity_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(entity_dir)
        size = _fmt_size(path.stat().st_size)
        extra = ""
        if path.suffix == ".json":
            extra = _json_field_count(path)
        tree.add(f"{rel}  [dim]{size}{extra}[/dim]")

    _ = schema  # kept for future schema-aware annotations
    console.print(tree)


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}k"
    return f"{n / (1024 * 1024):.1f}M"


def _json_field_count(path: Path) -> str:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    if isinstance(data, dict):
        return f" · {len(data)} fields"
    if isinstance(data, list):
        return f" · {len(data)} items"
    return ""


# ---------------------------------------------------------------------------
# role
# ---------------------------------------------------------------------------


def _inspect_role(
    config: str = typer.Option(_DEFAULT_CONFIG, "--config", "-c"),
) -> None:
    """Print REIGNER.md content + resolved path + configured skills list.

    Composed ROLE (file + active skills + dynamic context) is deferred to
    T-31 when the skills loader lands; the header below signals that.
    """
    cfg = _load_config(Path(config))
    console = Console()

    role_path = cfg.resolve(cfg.role.file)
    skills = cfg.role.skills

    console.print(f"[dim]file:   {role_path}[/dim]")
    if skills:
        console.print(f"[dim]skills: {', '.join(skills)}[/dim]")
    else:
        console.print("[dim]skills: (none configured)[/dim]")
    console.print("[dim]" + "─" * 40 + "[/dim]")

    if not role_path.exists():
        console.print(f"[yellow]REIGNER.md not found at {role_path}[/yellow]")
        return

    console.print(role_path.read_text())

    if skills:
        console.print("[dim]" + "─" * 40 + "[/dim]")
        console.print(
            "[dim](composed ROLE = REIGNER.md + active skill blocks + dynamic context — "
            "skills loader lands with T-31; this prints the source file only.)[/dim]"
        )


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------


def _inspect_tools(
    config: str = typer.Option(_DEFAULT_CONFIG, "--config", "-c"),
) -> None:
    """Enumerate tools as the harness would wire them from this config.

    Today wires: ``tools.custom`` (dotted paths to @tool-decorated callables).
    Deferred (surfaced as notes): ``tools.artifacts`` (T-09), ``tools.search``
    (T-10).
    """
    cfg = _load_config(Path(config))
    console = Console()

    specs: list[tuple[ToolSpec, str]] = []
    for dotted in cfg.tools.custom:
        try:
            obj = _import_dotted(dotted)
        except (ImportError, AttributeError) as e:
            console.print(f"[red]✗[/red] {dotted}: {e}")
            continue
        spec = getattr(obj, "__reigner_spec__", None)
        if not isinstance(spec, ToolSpec):
            console.print(
                f"[red]✗[/red] {dotted}: not a @tool-decorated callable (no __reigner_spec__)"
            )
            continue
        specs.append((spec, dotted))

    if specs:
        table = Table(title="custom tools", show_header=True, header_style="bold")
        table.add_column("name")
        table.add_column("readonly", justify="center")
        table.add_column("pseudo", justify="center")
        table.add_column("cache", justify="center")
        table.add_column("source")
        for spec, dotted in specs:
            table.add_row(
                spec.name,
                _yn(spec.readonly),
                _yn(spec.pseudo),
                _yn(spec.cache),
                f"[dim]{dotted}[/dim]",
            )
        console.print(table)
    else:
        console.print("[dim]no custom tools configured in reigner.yaml[/dim]")

    deferred: list[str] = []
    if cfg.tools.artifacts is not None:
        a = cfg.tools.artifacts
        deferred.append(
            f"  artifacts → root={a.root}, schema={a.schema_path}"
            "  [deferred: T-09 ArtifactStore builders]"
        )
    if cfg.tools.search is not None:
        deferred.append(
            f"  search → type={cfg.tools.search.type}, index_path={cfg.tools.search.index_path}"
            "  [deferred: T-10 BM25 builders]"
        )
    if deferred:
        console.print("\n[dim]configured but not yet wired:[/dim]")
        for line in deferred:
            console.print(f"[dim]{line}[/dim]")


def _yn(v: bool) -> str:
    return "✓" if v else ""


def _import_dotted(dotted: str) -> Any:
    """Resolve 'pkg.mod:attr' or 'pkg.mod.attr' to an attribute.

    Mirrors ``reigner.types.import_dotted`` but kept local to avoid a hard
    dependency on that helper's exact signature.
    """
    if ":" in dotted:
        mod_path, _, attr = dotted.partition(":")
    elif "." in dotted:
        mod_path, _, attr = dotted.rpartition(".")
    else:
        raise ImportError(f"not a dotted path: {dotted!r}")
    mod = import_module(mod_path)
    return getattr(mod, attr)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def _inspect_config(
    config: str = typer.Option(_DEFAULT_CONFIG, "--config", "-c"),
) -> None:
    """Render the resolved config: settings table + summary of other blocks."""
    cfg = _load_config(Path(config))
    console = Console()

    console.print(f"[bold]{cfg.name}[/bold]  [dim]v{cfg.version}[/dim]")
    if cfg.config_path is not None:
        console.print(f"[dim]config: {cfg.config_path}[/dim]")
    console.print()

    # model
    model_line = f"model: {cfg.model.provider}:{cfg.model.name}  (temp={cfg.model.temperature})"
    console.print(model_line)
    if cfg.oracle is not None:
        console.print(f"oracle: {cfg.oracle.provider}:{cfg.oracle.model}")

    # role
    console.print(f"role.file: {cfg.role.file}")
    if cfg.role.skills:
        console.print(f"role.skills: {', '.join(cfg.role.skills)}")

    # tools summary
    if cfg.tools.artifacts is not None:
        console.print(f"tools.artifacts.root: {cfg.tools.artifacts.root}")
    if cfg.tools.search is not None:
        console.print(f"tools.search.index_path: {cfg.tools.search.index_path}")
    if cfg.tools.custom:
        console.print(f"tools.custom: {len(cfg.tools.custom)} dotted-path(s)")

    # sessions
    console.print(f"sessions.store_path: {cfg.sessions.store_path}")

    console.print()
    # settings table — file vs default origin
    table = Table(title="settings", show_header=True, header_style="bold")
    table.add_column("field")
    table.add_column("value")
    table.add_column("source", justify="center")
    for origin in cfg.settings.describe():
        source = "file" if origin.from_file else "[dim]default[/dim]"
        table.add_row(origin.name, _fmt_value(origin.value), source)
    console.print(table)


def _fmt_value(value: object) -> str:
    if isinstance(value, dict) and not value:
        return "{}"
    if isinstance(value, tuple | list) and not value:
        return "[]"
    return repr(value)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _die(msg: str, code: int) -> NoReturn:
    typer.echo(f"✗ {msg}", err=True)
    raise typer.Exit(code)
