"""Meta commands: version and any other always-on introspection."""

from __future__ import annotations

import typer

import reigner


def register(app: typer.Typer) -> None:
    app.command("version")(_version)


def _version() -> None:
    """Print the installed reigner version."""
    typer.echo(reigner.__version__)
