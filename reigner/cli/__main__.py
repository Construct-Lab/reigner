"""CLI entry point. Each command lives in its own module and self-registers."""

from __future__ import annotations

import typer

from reigner.cli import _meta, chat, ingest, init, inspect

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
# T-21+ append more register() calls here.


def main() -> None:
    app()


if __name__ == "__main__":
    main()
