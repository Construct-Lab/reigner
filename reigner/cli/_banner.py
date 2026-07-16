"""Startup banner for ``reigner chat`` — crown logo + the loaded config.

Printed once when the interactive REPL boots so the operator can see, at a
glance, which project / model / config they're actually talking to. This is
pure presentation: it reloads ``reigner.yaml`` (cheap) rather than threading
config state through the harness, and reads tool availability off the live
registry so the count matches what this session can actually call.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from reigner.config import ReignerConfig
from reigner.harness.agent import Session

# The brand crown (assets/reigner-icon-*.svg): five spikes — tall centre, near-tall
# outers, shorter mids — a diamond in the body, and a dotted band below. Aligned to
# a fixed 17-column width so the block stays rectangular next to the info column.
_CROWN = (
    "  ▙     ▲     ▟  ",
    "  █▙ ▲ ▟█▙ ▲ ▟█  ",
    "  ██▙▟██◈██▙▟██  ",
    "  ▌ • • • • • ▐  ",
    "  ▙▄▄▄▄▄▄▄▄▄▄▄▟  ",
)


def _rel(path: Path) -> str:
    """Path relative to cwd when possible, else the bare name."""
    try:
        return str(path.resolve().relative_to(Path.cwd()))
    except ValueError:
        return path.name


def render_banner(console: Console, session: Session, config_path: Path) -> None:
    """Print the chat startup banner: crown logo beside the loaded config."""
    try:
        cfg = ReignerConfig.load(config_path)
    except Exception:  # noqa: BLE001 — a banner must never block the REPL
        return

    tools_n = len(session.harness.registry.for_profile(session.profile))
    role_path = (config_path.parent / cfg.role.file).resolve()
    role_exists = role_path.exists()

    logo = Text()
    for i, line in enumerate(_CROWN):
        logo.append(line + "\n", style="gold1" if i < 3 else "yellow")

    info = Text()
    info.append("reigner", style="bold magenta")
    info.append(f"  v{cfg.version}\n", style="dim")

    info.append(cfg.name, style="bold white")
    if role_exists:
        info.append(f"  ·  {cfg.role.file}", style="dim")
    else:
        info.append(f"  ·  {cfg.role.file} (missing)", style="yellow")
    if cfg.role.skills:
        info.append(f" · {len(cfg.role.skills)} skills", style="dim")
    info.append("\n")

    info.append(cfg.model.provider, style="cyan")
    info.append(f":{cfg.model.name}", style="bold cyan")
    info.append(f"  ·  temp {cfg.model.temperature}", style="dim")
    if cfg.oracle is not None:
        info.append(f"  ·  oracle {cfg.oracle.model}", style="dim")
    info.append("\n")

    info.append(f"{tools_n} tools", style="green")
    info.append(f"  ·  {_rel(config_path)}", style="dim")

    grid = Table.grid(padding=(0, 2))
    grid.add_column()
    grid.add_column()
    grid.add_row(logo, info)

    console.print()
    console.print(grid)
    console.print()
