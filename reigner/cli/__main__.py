"""CLI entry point. Each command lives in its own module and self-registers."""

from __future__ import annotations

import typer

from reigner.cli import _meta, chat, ingest, init, inspect, serve, session
from reigner.cli import eval as eval_cmd

app = typer.Typer(
    name="reigner",
    help="Single-agent, retrieval-shaped, citation-faithful agents over compiled knowledge.",
    no_args_is_help=True,
)

_meta.register(app)
init.register(app)
chat.register(app)
ingest.register(app)
inspect.register(app)
serve.register(app)
eval_cmd.register(app)
session.register(app)


def main() -> None:
    """Entry point for the ``reigner`` console script."""
    app()


if __name__ == "__main__":
    main()
