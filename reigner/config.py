"""``reigner.yaml`` schema, loader, and validation.

Single source of truth for an agent's configuration. Mirrors SPEC §13.

Design notes:
- Pydantic v2 with ``extra="forbid"`` everywhere — typos in YAML fail loudly.
- ``SettingsConfig`` owns all loop-budget defaults; ``Harness`` holds one and
  reads off it, so defaults can't drift (see ``docs/t-17-implementation-plan.html``).
- No env-var interpolation — adapter SDKs read API keys from the environment
  themselves.
- ``role.cascade`` is hard-rejected with a message citing SPEC §9 / §22 Q9.
- Paths in the model stay as strings; resolve against ``config_path.parent``
  via :meth:`ReignerConfig.resolve`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_validator,
)

from reigner.types import ConfigError, DottedPath, ProviderName

# ---------------------------------------------------------------------------
# Leaf models
# ---------------------------------------------------------------------------


class ModelConfig(BaseModel):
    """LLM provider + model selection for the main loop."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderName
    name: str
    temperature: float = 0.2

    @field_validator("name")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("model.name must be non-empty")
        return v


class OracleConfig(BaseModel):
    """Optional single-turn escalation model (SPEC §5.5)."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderName
    model: str

    @field_validator("model")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("oracle.model must be non-empty")
        return v


class SettingsConfig(BaseModel):
    """Loop budgets and thresholds. Single source of truth for defaults.

    ``Harness`` holds one of these in its ``settings`` field and reads
    individual knobs off it. Keep this list in sync with SPEC §13.
    """

    model_config = ConfigDict(extra="forbid")

    max_iterations: int = Field(default=25, gt=0)
    context_budget_tokens: int = Field(default=100_000, gt=0)
    max_tool_result_chars: int = Field(default=4_000, gt=0)
    tool_result_char_limits: dict[str, int] = Field(default_factory=dict)
    nudge_interval: int = Field(default=3, gt=0)
    max_consecutive_errors: int = Field(default=3, gt=0)
    max_session_notes: int = Field(default=20, gt=0)
    history_keep_recent: int = Field(default=3, gt=0)
    compaction_thresholds: tuple[float, float, float] = (0.80, 0.90, 0.95)
    parallel_reads: bool = True
    timeout_seconds: int = Field(default=120, gt=0)

    @field_validator("tool_result_char_limits")
    @classmethod
    def _positive_limits(cls, v: dict[str, int]) -> dict[str, int]:
        for tool_name, limit in v.items():
            if limit <= 0:
                raise ValueError(f"tool_result_char_limits[{tool_name!r}] must be > 0, got {limit}")
        return v

    @field_validator("compaction_thresholds")
    @classmethod
    def _monotonic_thresholds(cls, v: tuple[float, float, float]) -> tuple[float, float, float]:
        if not all(0.0 < t < 1.0 for t in v):
            raise ValueError(f"compaction_thresholds must each be in (0, 1), got {v}")
        if not (v[0] < v[1] < v[2]):
            raise ValueError(f"compaction_thresholds must be strictly increasing, got {v}")
        return v

    def describe(self) -> list[FieldOrigin]:
        """Return each field with its value and whether it was set explicitly.

        Consumed by T-20 ``reigner inspect config`` so users can see which
        values came from ``reigner.yaml`` vs. defaults.
        """
        set_fields = self.model_fields_set
        return [
            FieldOrigin(
                name=name,
                value=getattr(self, name),
                from_file=name in set_fields,
            )
            for name in type(self).model_fields
        ]


@dataclass(frozen=True)
class FieldOrigin:
    """One row of :meth:`SettingsConfig.describe` output."""

    name: str
    value: Any
    from_file: bool


class RoleConfig(BaseModel):
    """Where to find REIGNER.md and which skills to load.

    ``cascade`` is explicitly rejected — SPEC §9 / §22 Q9 resolved that there
    is no runtime cascade. Recipes are init-time scaffolds, not runtime sources.
    """

    model_config = ConfigDict(extra="forbid")

    file: str = "REIGNER.md"
    skills: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _reject_cascade(cls, data: Any) -> Any:
        if isinstance(data, dict) and "cascade" in data:
            raise ValueError(
                "role.cascade was removed (SPEC §9, §22 Q9). REIGNER.md is the "
                "single runtime source of truth; recipes are init-time scaffolds "
                "only. Drop the `cascade:` key."
            )
        return data


class ArtifactsToolsConfig(BaseModel):
    """``tools.artifacts`` — bound to ``ArtifactStore``."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    root: str
    schema_path: str = Field(alias="schema")


class SearchToolsConfig(BaseModel):
    """``tools.search`` — bound to a ``SearchIndex`` (``bm25`` today)."""

    model_config = ConfigDict(extra="forbid")

    type: str = "bm25"
    index_path: str


class FsToolsConfig(BaseModel):
    """``tools.fs`` — bound to :class:`reigner.tools.fs.FsTools`.

    ``root`` is the sandbox directory the agent is allowed to see; resolved
    relative to the config file. ``write_enabled`` toggles whether
    :func:`fs_write` is exposed (defaults off — read-only is the safe default).

    FsTools' other knobs (per-call caps, text-extension allowlist, ignored
    dirs) stay at library defaults for now; promote them into this block when
    a real project needs to tune them.
    """

    model_config = ConfigDict(extra="forbid")

    root: str
    write_enabled: bool = False


class ToolsConfig(BaseModel):
    """Tool surfaces to wire into the harness.

    All sub-sections optional. ``custom`` is a list of dotted-path imports
    resolved via :func:`reigner.types.import_dotted`.
    """

    model_config = ConfigDict(extra="forbid")

    artifacts: ArtifactsToolsConfig | None = None
    search: SearchToolsConfig | None = None
    fs: FsToolsConfig | None = None
    custom: list[DottedPath] = Field(default_factory=list)


class SessionsConfig(BaseModel):
    """Where session JSONL files live and whether to auto-save."""

    model_config = ConfigDict(extra="forbid")

    store_path: str = "./.reigner/sessions"
    auto_save: bool = True


class EvalConfig(BaseModel):
    """``reigner eval`` configuration."""

    model_config = ConfigDict(extra="forbid")

    cases: str = "eval/cases.yaml"
    checks: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


class ReignerConfig(BaseModel):
    """Validated ``reigner.yaml`` tree.

    Construct via :meth:`load` to get path-resolution and friendly error
    messages. The instance also carries the source ``config_path`` so
    relative paths inside the config can be resolved against it.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str = "0.1.0"
    model: ModelConfig
    oracle: OracleConfig | None = None
    settings: SettingsConfig = Field(default_factory=SettingsConfig)
    role: RoleConfig = Field(default_factory=RoleConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    sessions: SessionsConfig = Field(default_factory=SessionsConfig)
    plugins: list[DottedPath] = Field(default_factory=list)
    eval: EvalConfig | None = None

    _config_path: Path | None = PrivateAttr(default=None)
    """Set by :meth:`load`. ``None`` when the config was built in-memory."""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> ReignerConfig:
        """Read, parse, validate. Raises :class:`ConfigError` on any failure."""
        p = Path(path)
        try:
            raw = p.read_text()
        except OSError as e:
            raise ConfigError(f"cannot read config file {p}: {e}") from e

        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            raise ConfigError(f"cannot parse YAML in {p}: {e}") from e

        if not isinstance(data, dict):
            raise ConfigError(f"config root must be a mapping, got {type(data).__name__} in {p}")

        try:
            cfg = cls.model_validate(data)
        except ValidationError as e:
            raise ConfigError(_format_validation_error(p, e)) from e

        cfg._config_path = p.resolve()
        return cfg

    @classmethod
    def write_default(cls, path: str | Path, name: str = "my_agent") -> Path:
        """Emit the canonical scaffold yaml used by ``reigner init``.

        Round-trips through :meth:`load` without error. Kept here (not in T-18)
        so the schema and its scaffold can't drift.
        """
        p = Path(path)
        p.write_text(_DEFAULT_YAML_TEMPLATE.format(name=name))
        return p

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------
    @property
    def config_path(self) -> Path | None:
        return self._config_path

    def resolve(self, sub_path: str | Path) -> Path:
        """Resolve a relative path against the config file's parent directory.

        Absolute paths pass through unchanged. If the config was constructed
        in memory (no ``_config_path``), resolves against the current working
        directory.
        """
        sub = Path(sub_path)
        if sub.is_absolute():
            return sub
        base = self._config_path.parent if self._config_path else Path.cwd()
        return (base / sub).resolve()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_validation_error(path: Path, err: ValidationError) -> str:
    """Human-readable summary of a Pydantic ValidationError.

    Pydantic's default repr is dense; we surface the file path and the first
    handful of errors with their dotted location so users can find the typo.
    """
    lines = [f"invalid config at {path}:"]
    for e in err.errors()[:5]:
        loc = ".".join(str(p) for p in e["loc"]) or "<root>"
        lines.append(f"  - {loc}: {e['msg']}")
    extra = len(err.errors()) - 5
    if extra > 0:
        lines.append(f"  ... and {extra} more")
    return "\n".join(lines)


_DEFAULT_YAML_TEMPLATE = """\
name: {name}
version: 0.1.0

model:
  provider: openai
  name: gpt-4o
  temperature: 0.2

# oracle: optional single-turn escalation (SPEC §5.5)
# oracle:
#   provider: anthropic
#   model: claude-opus-4-7

settings:
  max_iterations: 25
  context_budget_tokens: 100000
  max_tool_result_chars: 4000
  nudge_interval: 3
  max_consecutive_errors: 3
  compaction_thresholds: [0.80, 0.90, 0.95]
  parallel_reads: true

role:
  file: REIGNER.md
  skills: []

tools:
  # artifacts:
  #   root: library/artifacts
  #   schema: ./schema.yaml
  # search:
  #   type: bm25
  #   index_path: search-index/documents.json
  # fs:
  #   root: .
  #   write_enabled: false
  custom: []

sessions:
  store_path: ./.reigner/sessions
  auto_save: true

plugins: []
"""


__all__ = [
    "ArtifactsToolsConfig",
    "ConfigError",
    "EvalConfig",
    "FieldOrigin",
    "FsToolsConfig",
    "ModelConfig",
    "OracleConfig",
    "ReignerConfig",
    "RoleConfig",
    "SearchToolsConfig",
    "SessionsConfig",
    "SettingsConfig",
    "ToolsConfig",
]
