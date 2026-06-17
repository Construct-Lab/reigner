"""`reigner eval` — run the eval suite and print a scorecard (SPEC §13, §15).

    reigner eval                         all cases, configured (or all) checks
    reigner eval --case amity_faculty    run one case (repeatable)
    reigner eval --check faithfulness    run one check (repeatable)
    reigner eval --json                  ND-JSON-free structured result on stdout

Cases come from ``eval.cases`` in ``reigner.yaml`` (default ``eval/cases.yaml``).
Checks come from ``--check`` if given, else ``eval.checks`` from config, else every
registered check. Builds the harness from config exactly like ``reigner chat``, so
a real run needs the model's API key in the environment / ``.env``.

Exit codes mirror the other commands: 0 every case passed, 1 some case failed,
2 usage error (missing config/cases, unknown case/check name, empty suite).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import typer

from reigner.cli._env import load_project_env
from reigner.eval import (
    EvalSuite,
    SuiteResult,
    registered_checks,
    render_report,
    render_scorecard,
)
from reigner.eval.cases import EvalCase
from reigner.harness.agent import Harness
from reigner.tools.registry import Profile
from reigner.types import ConfigError

if TYPE_CHECKING:
    from reigner.config import ReignerConfig

_DEFAULT_CONFIG = "reigner.yaml"
_DEFAULT_CASES = "eval/cases.yaml"
_PROFILES = ("full", "read_only", "eval")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def register(app: typer.Typer) -> None:
    app.command("eval")(_eval)


def _eval(
    case: Annotated[
        list[str] | None,
        typer.Option("--case", metavar="ID", help="Run only this case id (repeatable)."),
    ] = None,
    check: Annotated[
        list[str] | None,
        typer.Option("--check", metavar="NAME", help="Run only this check (repeatable)."),
    ] = None,
    profile: str = typer.Option(
        "eval",
        "--profile",
        help="Tool profile: eval (deterministic, no clarification), read_only, or full.",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the result as JSON instead of the markdown scorecard."
    ),
    report: bool = typer.Option(
        False,
        "--report",
        help="Emit a detailed markdown report (query, response, trace, citations) per case.",
    ),
    config: str = typer.Option(
        _DEFAULT_CONFIG, "--config", "-c", help="Path to reigner.yaml (defaults to ./reigner.yaml)."
    ),
) -> None:
    """Run the eval suite against the configured harness and print a scorecard."""
    if profile not in _PROFILES:
        typer.echo(f"✗ --profile must be one of {', '.join(_PROFILES)}; got {profile!r}", err=True)
        raise typer.Exit(EXIT_USAGE)
    if json_output and report:
        typer.echo("✗ pass at most one of --json / --report", err=True)
        raise typer.Exit(EXIT_USAGE)

    config_path = Path(config)
    cfg = _load_config(config_path)

    cases_path = config_path.parent / (cfg.eval.cases if cfg.eval else _DEFAULT_CASES)
    suite = _load_suite(cases_path, only=set(case or []))

    checks = _resolve_checks(
        requested=list(check or []), configured=cfg.eval.checks if cfg.eval else []
    )

    load_project_env(config_path)
    try:
        harness = Harness.from_config(config_path)
    except ConfigError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(EXIT_USAGE) from e

    result = asyncio.run(suite.run(harness, checks=checks, profile=cast(Profile, profile)))

    if json_output:
        print(json.dumps(_as_dict(result), indent=2))
    elif report:
        print(render_report(result))
    else:
        print(render_scorecard(result))

    raise typer.Exit(EXIT_OK if result.passed else EXIT_FAILED)


# ---------------------------------------------------------------------------
# Loading / resolution
# ---------------------------------------------------------------------------


def _load_config(config_path: Path) -> ReignerConfig:
    from reigner.config import ReignerConfig

    if not config_path.exists():
        typer.echo(
            f"✗ no {config_path} in {config_path.parent.resolve()} — "
            f"run `reigner init <name> --blank` first",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)
    try:
        return ReignerConfig.load(config_path)
    except ConfigError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(EXIT_USAGE) from e


def _load_suite(cases_path: Path, *, only: set[str]) -> EvalSuite:
    if not cases_path.exists():
        typer.echo(f"✗ no eval cases at {cases_path}", err=True)
        raise typer.Exit(EXIT_USAGE)
    try:
        suite = EvalSuite.from_yaml(cases_path)
    except (ValueError, OSError) as e:
        typer.echo(f"✗ failed to load cases: {e}", err=True)
        raise typer.Exit(EXIT_USAGE) from e

    cases: list[EvalCase] = suite.cases
    if only:
        known = {c.id for c in cases}
        unknown = only - known
        if unknown:
            typer.echo(
                f"✗ unknown case id(s): {', '.join(sorted(unknown))}. "
                f"Available: {', '.join(sorted(known)) or '(none)'}",
                err=True,
            )
            raise typer.Exit(EXIT_USAGE)
        cases = [c for c in cases if c.id in only]

    if not cases:
        typer.echo(f"✗ no eval cases to run in {cases_path}", err=True)
        raise typer.Exit(EXIT_USAGE)
    return EvalSuite(cases)


def _resolve_checks(*, requested: list[str], configured: list[str]) -> list[str]:
    """``--check`` wins, else config's ``eval.checks``, else every registered check."""
    chosen = requested or configured or registered_checks()
    available = set(registered_checks())
    unknown = [c for c in chosen if c not in available]
    if unknown:
        typer.echo(
            f"✗ unknown check(s): {', '.join(unknown)}. "
            f"Registered: {', '.join(registered_checks())}",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)
    return chosen


# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------


def _as_dict(result: SuiteResult) -> dict[str, object]:
    return {
        "passed": result.passed,
        "n_passed": result.n_passed,
        "n_failed": result.n_failed,
        "cases": [
            {
                "id": cr.case.id,
                "passed": cr.passed,
                "checks": [
                    {"name": r.name, "status": r.status, "detail": r.detail} for r in cr.results
                ],
            }
            for cr in result.cases
        ],
    }
