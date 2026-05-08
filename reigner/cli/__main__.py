import typer

import reigner

app = typer.Typer(
    name="reigner",
    help="Single-agent, retrieval-shaped, citation-faithful agents over compiled knowledge.",
    no_args_is_help=True,
)


@app.callback()
def _root() -> None:
    """Reigner CLI."""


@app.command()
def version() -> None:
    """Print the installed reigner version."""
    typer.echo(reigner.__version__)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
