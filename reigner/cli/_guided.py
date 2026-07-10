"""Guided init — the default mode for ``reigner init``.

Flow:

1. Auto-detect a model provider from the environment (a key already exported,
   or one seeded from a project ``.env`` by :func:`load_project_env`). No key
   anywhere → print setup instructions, offer ``--blank``, exit 0.
2. Interactive Q&A: domain / source documents / question shape as free text,
   citation strictness as a closed choice.
3. Two focused model calls generate ``REIGNER.md`` and ``schema.yaml``. The
   schema is validated through :meth:`ArtifactSchema.from_yaml` before it is
   written — a generated file that won't load never reaches disk.
4. Scaffold the project layout, then an explicit y/n gate before the only
   code-bearing file, ``extractors/my_extractor.py`` (the static blank stub —
   no model writes executable Python here).

Citation strictness shapes only the generated ``REIGNER.md`` prose;
``reigner.yaml`` stays the canonical default. Wiring the ``citation_strict``
skill is the documented upgrade path once skills ship.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path
from typing import Final

import typer
import yaml
from rich.console import Console
from rich.prompt import Prompt as RichPrompt

from reigner.artifacts.schema import ArtifactSchema
from reigner.cli._env import load_project_env
from reigner.harness.adapters.base import AdapterError, ModelAdapter
from reigner.harness.state import Prompt, Turn
from reigner.types import ProviderName

# Probe order is deliberate priority, not alphabetical: a present ANTHROPIC key
# wins over OPENAI. Each provider maps to a sane generation default (overridable
# later in the project's reigner.yaml). Gemini honours either env var.
_DETECT: Final[list[tuple[tuple[str, ...], ProviderName, str]]] = [
    (("ANTHROPIC_API_KEY",), "anthropic", "claude-sonnet-4-6"),
    (("OPENAI_API_KEY",), "openai", "gpt-5.5"),
    (("GEMINI_API_KEY", "GOOGLE_API_KEY"), "gemini", "gemini-3.5-flash"),
]

_STRICTNESS_CHOICES: Final = ["strict", "balanced", "lenient"]
_UNIFORMITY_CHOICES: Final = ["uniform", "mixed"]

# The static map-reduce extractor template, scaffolded in place of the
# single-shot stub when the corpus is mixed (see _read_template / run_guided).
# It lives outside templates/blank so the normal scaffold walk never copies it.
_MAPREDUCE_TEMPLATE: Final = "my_extractor_mapreduce.py"

_ROLE_SYS: Final = """\
You are scaffolding a Reigner project's REIGNER.md — the single instruction
file that defines a retrieval agent's runtime behavior. It is loaded once at
session start and shapes every answer the agent gives.

Given the developer's answers below, write a complete REIGNER.md in Markdown
with exactly these level-2 sections, in order:

## Identity
## Retrieval grammar
## Citation rules
## Clarification policy

Write concrete, directive prose the model will actually follow — tailored to
the stated domain, not generic boilerplate. The Retrieval grammar section
should teach the targeted-retrieval pattern (structured fields first, then
locate, then read in bounded chunks). The Citation rules section must reflect
the requested citation strictness exactly.

Output ONLY the Markdown file content. No code fences, no preamble, no
trailing commentary."""

_SCHEMA_SYS: Final = """\
You are scaffolding a Reigner project's schema.yaml, which declares the shape
of compiled artifacts and is loaded by ArtifactSchema.from_yaml.

Given the developer's answers below, output a valid schema.yaml with these
top-level keys:

  entity_path: a string template naming the artifact's identity dimensions,
    e.g. "{entity_id}/{version}" or "{ticker}/{fiscal_year}".
  sections: a list of mappings, each {name: str, required: bool} and an
    optional max_chars: int. Use "section/subsection" style names.
  json_artifacts: a list of mappings, each {name: "<file>.json", fields:
    {field_name: type}} where type is one of str, int, float, bool.

Choose dimensions, sections, and fields that genuinely fit the domain.

Output ONLY the YAML. No code fences, no preamble, no commentary."""


@dataclass(frozen=True)
class GuidedAnswers:
    """The inputs collected from the interactive Q&A.

    ``uniformity`` selects the schema shape: ``"uniform"`` (the default) keeps
    the model-generated schema as-is; ``"mixed"`` layers it onto a generic
    baseline so a heterogeneous corpus doesn't dead-letter on required sections.
    """

    domain: str
    sources: str
    questions: str
    strictness: str
    uniformity: str = "uniform"

    def as_brief(self) -> str:
        return (
            f"Domain: {self.domain}\n"
            f"Source documents: {self.sources}\n"
            f"Typical questions: {self.questions}\n"
            f"Citation strictness: {self.strictness}"
        )


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------


def _detect_provider() -> tuple[ProviderName, str] | None:
    """First provider whose API key is present, with its default gen model.

    ``load_project_env`` has already seeded ``os.environ`` from any project
    ``.env``, so this is a plain environment lookup.
    """
    for env_vars, provider, model in _DETECT:
        if any(os.environ.get(v) for v in env_vars):
            return provider, model
    return None


def _print_no_key(console: Console, name: str) -> None:
    console.print(
        "[yellow]![/yellow] Guided init needs a model API key — none found in the "
        "environment or ./.env\n"
    )
    console.print("  Set one of:")
    console.print("    [dim]export[/dim] ANTHROPIC_API_KEY=…")
    console.print("    [dim]export[/dim] OPENAI_API_KEY=…")
    console.print("    [dim]export[/dim] GEMINI_API_KEY=…\n")
    console.print(f"  Then re-run:  [bold]reigner init {name}[/bold]\n")
    console.print(f"  Or scaffold offline now:  [bold]reigner init {name} --blank[/bold]")


# ---------------------------------------------------------------------------
# Interactive Q&A
# ---------------------------------------------------------------------------


def _collect_answers(console: Console) -> GuidedAnswers:
    console.print("  Let's tailor your agent. Five quick questions.\n")
    domain = RichPrompt.ask("[bold]?[/bold] What domain will this agent work over")
    sources = RichPrompt.ask("[bold]?[/bold] What do your source documents look like")
    questions = RichPrompt.ask("[bold]?[/bold] What kinds of questions will users ask")
    strictness = RichPrompt.ask(
        "[bold]?[/bold] How strict should citations be",
        choices=_STRICTNESS_CHOICES,
        default="balanced",
    )
    uniformity = RichPrompt.ask(
        "[bold]?[/bold] Is your corpus uniform (same kind of document) or mixed",
        choices=_UNIFORMITY_CHOICES,
        default="uniform",
    )
    return GuidedAnswers(
        domain=domain.strip(),
        sources=sources.strip(),
        questions=questions.strip(),
        strictness=strictness,
        uniformity=uniformity,
    )


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _strip_fences(text: str) -> str:
    """Drop a leading ```lang fence and its closing ``` if the model added one."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip() + "\n"


async def _call(adapter: ModelAdapter, system: str, user_text: str) -> str:
    """One degenerate no-tools call (same shape as LLMExtractor.call_model)."""
    prompt = Prompt(
        stable=system,
        dynamic_context={},
        messages=[Turn(role="user", content=user_text)],
    )
    action = await adapter.call(prompt, [])
    return action.text or ""


def _layer_mixed_schema(yaml_text: str) -> str:
    """Rewrite a generated schema into the layered mixed-corpus shape.

    A mixed corpus has no single required-section list that fits every document,
    so a rigid schema dead-letters most of it. This prepends
    :meth:`ArtifactSchema.generic_default`'s sections as a baseline (one required
    summary any document can fill, plus optional generics) and appends the
    model's domain sections **forced optional** and **deduped** against the
    baseline.

    The same "nothing rigidly required" rule extends to JSON artifacts: declared
    ``fields`` are required by default, so a generated ``json_artifacts`` entry
    with fields would dead-letter any document the extractor can't fully populate
    — the exact failure the mixed branch exists to avoid. Each artifact is
    therefore relaxed to ``required_fields: []`` (fields stay declared and
    type-checked when present, just not mandatory). ``entity_path`` is untouched.
    """
    data = yaml.safe_load(yaml_text)
    if not isinstance(data, dict):
        raise ValueError(f"schema YAML must be a mapping, got {type(data).__name__}")

    baseline = [
        {"name": s.name, "required": s.required} for s in ArtifactSchema.generic_default().sections
    ]
    baseline_names = {s["name"] for s in baseline}
    domain = [
        {**s, "required": False}  # the model defaults to required:true — force it off
        for s in (data.get("sections") or [])
        if isinstance(s, dict) and s.get("name") not in baseline_names
    ]
    data["sections"] = baseline + domain

    for artifact in data.get("json_artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("fields"):
            artifact["required_fields"] = []  # mixed: never dead-letter on JSON fields

    return yaml.safe_dump(data, sort_keys=False)


def _read_template(rel: str) -> str:
    """Read a static template file shipped alongside the blank scaffold."""
    with as_file(files("reigner.cli.templates") / rel) as path:
        return Path(path).read_text()


def _validate_schema(yaml_text: str) -> None:
    """Raise if ``yaml_text`` won't load as an ArtifactSchema."""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tmp:
        tmp.write(yaml_text)
        tmp_path = tmp.name
    try:
        ArtifactSchema.from_yaml(tmp_path)
    finally:
        os.unlink(tmp_path)


async def _generate(
    console: Console, adapter: ModelAdapter, answers: GuidedAnswers
) -> tuple[str, str]:
    """Generate ``(REIGNER.md, schema.yaml)``.

    The schema is validated; one retry feeds the loader's error back to the
    model before we give up.
    """
    brief = answers.as_brief()

    console.print("[dim]…[/dim] Generating REIGNER.md")
    role_md = _strip_fences(await _call(adapter, _ROLE_SYS, brief))

    console.print("[dim]…[/dim] Generating schema.yaml")
    last_err: str | None = None
    for _attempt in range(2):
        user = (
            brief
            if last_err is None
            else (
                f"{brief}\n\nYour previous schema.yaml failed to load with:\n"
                f"{last_err}\nReturn a corrected schema.yaml."
            )
        )
        schema_yaml = _strip_fences(await _call(adapter, _SCHEMA_SYS, user))
        try:
            if answers.uniformity == "mixed":
                schema_yaml = _layer_mixed_schema(schema_yaml)
                console.print("[dim]  ↳ layered for mixed corpus[/dim]")
            _validate_schema(schema_yaml)
            console.print("[dim]  ↳ schema validated[/dim]")
            return role_md, schema_yaml
        except Exception as exc:  # noqa: BLE001 — surface any loader failure
            last_err = str(exc)

    typer.echo(
        f"✗ guided init could not generate a valid schema.yaml: {last_err}\n"
        f"  Try again, or scaffold offline with --blank.",
        err=True,
    )
    raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_guided(name: str, *, force: bool) -> None:
    """Entry point dispatched from ``reigner init`` for the guided default."""
    # Imported here (not at module top) to avoid a cli.init ⇄ cli._guided cycle.
    from reigner.cli.init import _print_success, _scaffold, ensure_writable

    console = Console()
    target = Path(name)

    # Fail the non-empty check before the Q&A + model calls, not after.
    ensure_writable(target, force=force)

    load_project_env()  # seed os.environ from a CWD .env, if any (real env wins)

    detected = _detect_provider()
    if detected is None:
        _print_no_key(console, name)
        raise typer.Exit(0)

    provider, model = detected
    console.print(
        f"[green]✓[/green] Detected [bold]{provider}[/bold] from environment — "
        f"generating with {model}\n"
    )

    answers = _collect_answers(console)
    console.print()

    from reigner.harness.adapters import build_adapter

    adapter = build_adapter(provider, model)
    try:
        role_md, schema_yaml = asyncio.run(_generate(console, adapter, answers))
    except AdapterError as exc:
        typer.echo(f"✗ model call failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    console.print()
    stub = "extractors/my_extractor.py"
    include_extractor = typer.confirm(
        "Scaffold extractors/my_extractor.py? It's runnable Python you'll fill in later",
        default=False,
    )
    skip = set() if include_extractor else {stub}

    overrides = {"REIGNER.md": role_md, "schema.yaml": schema_yaml}
    # A mixed corpus needs whole-document extraction; offer the map-reduce
    # skeleton instead of the single-shot stub.
    if include_extractor and answers.uniformity == "mixed":
        overrides[stub] = _read_template(_MAPREDUCE_TEMPLATE)

    _scaffold(
        target,
        force=force,
        overrides=overrides,
        skip=skip,
    )
    console.print()
    _print_success(target, mode="guided")
