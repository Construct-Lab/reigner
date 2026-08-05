"""`reigner serve` — run the agent as an HTTP (SSE) or MCP server.

``reigner serve --http`` boots a uvicorn process over the FastAPI app
(:mod:`reigner.server.fastapi_app`), wiring one shared :class:`Harness` built
from ``reigner.yaml``. ``--mcp`` is reserved for the MCP export and currently
exits with a clear "not yet implemented" message rather than pretending to run.

``--http`` is the default when no transport flag is given.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

import typer

from reigner.cli._env import load_project_env
from reigner.config import ReignerConfig
from reigner.harness.agent import Harness
from reigner.types import ConfigError

_DEFAULT_CONFIG = "reigner.yaml"

# Exit codes mirror `reigner chat`: 2 = usage/config error.
EXIT_USAGE = 2


def register(app: typer.Typer) -> None:
    """Register the ``serve`` command on the given Typer app."""
    app.command("serve")(_serve)


def _serve(
    http: bool = typer.Option(
        False,
        "--http",
        help="Run the FastAPI HTTP server (SSE streaming). The default transport.",
    ),
    mcp: bool = typer.Option(
        False,
        "--mcp",
        help="Run as an MCP server (not yet implemented).",
    ),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Interface to bind. Defaults to loopback; set 0.0.0.0 to expose.",
    ),
    port: int = typer.Option(8000, "--port", help="Port to listen on."),
    config: str = typer.Option(
        _DEFAULT_CONFIG,
        "--config",
        "-c",
        help="Path to reigner.yaml (defaults to ./reigner.yaml).",
    ),
) -> None:
    """Serve the configured agent over HTTP (default) or MCP."""
    if mcp and http:
        typer.echo("✗ pick one transport: --http or --mcp", err=True)
        raise typer.Exit(EXIT_USAGE)
    if mcp:
        typer.echo(
            "✗ --mcp is not yet implemented — the MCP export lands in a later change.\n"
            "  Use `reigner serve --http` for now.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    cfg, harness = _load(Path(config))
    _run_http(cfg, harness, host=host, port=port)


def _load(config_path: Path) -> tuple[ReignerConfig, Harness]:
    """Read config (for /health identity) and build the harness from one file."""
    if not config_path.exists():
        typer.echo(
            f"✗ no {config_path} in {config_path.parent.resolve()} — "
            f"run `reigner init <name> --blank` first",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)
    load_project_env(config_path)
    try:
        cfg = ReignerConfig.load(config_path)
        harness = Harness.from_config(config_path)
    except ConfigError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(EXIT_USAGE) from e
    return cfg, harness


def _run_http(cfg: ReignerConfig, harness: Harness, *, host: str, port: int) -> None:
    # Imported lazily so `reigner` runs without the `server` extra installed;
    # only `serve --http` requires fastapi + uvicorn.
    import uvicorn

    from reigner.server.fastapi_app import create_app

    model = f"{cfg.model.provider}/{cfg.model.name}"
    app = create_app(harness, name=cfg.name, model=model)

    typer.echo(f"· reigner http server — {cfg.name} ({model})")
    if not _is_loopback(host):
        typer.echo(
            f"! bound to {host} with no auth, CORS, or rate limiting\n"
            f"  — put a gateway in front before exposing this.",
            err=True,
        )
    typer.echo(f"· listening on http://{host}:{port}")
    typer.echo(f"  ({' · '.join(_ROUTES)})")
    uvicorn.run(app, host=host, port=port)


_ROUTES = (
    "POST /run",
    "GET /sessions",
    "GET /sessions/{id}/events",
    "GET /health",
)


def _is_loopback(host: str) -> bool:
    """Whether ``host`` keeps the server on this machine.

    Anything else reaches the network, and the session endpoints serve every
    stored transcript — so that bind earns a warning. Unparseable hosts (a
    name, not an address) are treated as exposed: warning on a loopback alias
    is cheap, staying quiet on a public bind is not.
    """
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"
