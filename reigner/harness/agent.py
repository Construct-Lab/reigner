"""Public ``Harness`` and ``Session`` API (SPEC.md §5.1, issue #5).

``Harness`` is the immutable configured loop — model adapter, tools, role,
and a :class:`SettingsConfig` carrying every loop-budget knob. ``Session`` is
the mutable per-conversation container on top: it owns ``AgentState``, the
tool-result cache, and the event log.

T-17 reshape: the eleven loose budget fields that used to live on ``Harness``
collapsed into ``settings: SettingsConfig``. ``SettingsConfig`` is now the
single source of truth for defaults; ``Harness`` reads off it. See
``docs/t-17-implementation-plan.html``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from reigner.config import ReignerConfig, SettingsConfig
from reigner.harness.adapters.base import ModelAdapter
from reigner.harness.cache import ToolResultCache
from reigner.harness.events import Event, FinalAnswerEvent
from reigner.harness.loop import RunnableTool, run_loop
from reigner.harness.state import AgentState, Citation, Note, SteeringMode, Turn
from reigner.tools.registry import ToolRegistry
from reigner.types import ConfigError, Profile, ProviderName, import_dotted

if TYPE_CHECKING:
    pass


@dataclass(kw_only=True)
class Harness:
    """Immutable configured agent. Build once, spawn many sessions.

    All loop budgets live on :attr:`settings`. Construct a custom
    :class:`SettingsConfig` and pass it in to override defaults — or pass
    nothing and ride the defaults from SPEC §13.
    """

    adapter: ModelAdapter
    settings: SettingsConfig = field(default_factory=SettingsConfig)
    registry: ToolRegistry = field(default_factory=ToolRegistry)
    role: str = ""
    oracle_adapter: ModelAdapter | None = None

    @classmethod
    def from_config(
        cls,
        path: str | Path,
        tools: list[RunnableTool] | None = None,
    ) -> Harness:
        """Build a :class:`Harness` from a ``reigner.yaml`` file.

        Partial wiring in T-17 (post-T-09):

        - Model and oracle adapters are resolved via a lazy provider switch.
        - ``role.file`` is read from disk if present (resolved relative to the
          config file). Skill composition belongs to T-30 and is deferred.
        - ``tools.custom`` dotted paths are imported.
        - ``tools.artifacts`` is wired to a real :class:`ArtifactStore`;
          the six SPEC §6.4 read tools are appended to ``wired_tools``.
        - ``tools.search`` is wired to the configured :class:`SearchIndex`
          backend (``type: "bm25"`` is the only one known today).
        - Plugins (``cfg.plugins``) parse but are not yet wired.
        - Sessions / eval sections parse but the runtime that consumes them
          isn't on Harness yet.

        Tool wiring order: ``[artifact tools, search tools, custom tools, *(tools or [])]``.
        Names must be unique across sources — collisions raise
        :class:`ToolRegistrationError` from the registry.
        """
        cfg = ReignerConfig.load(path)

        adapter = _build_adapter(cfg.model.provider, cfg.model.name)
        oracle_adapter = (
            _build_adapter(cfg.oracle.provider, cfg.oracle.model)
            if cfg.oracle is not None
            else None
        )

        role_text = _load_role(cfg)

        artifact_tools: list[RunnableTool] = []
        if cfg.tools.artifacts is not None:
            artifact_tools = _build_artifact_tools(cfg)

        search_tools: list[RunnableTool] = []
        if cfg.tools.search is not None:
            search_tools = _build_search_tools(cfg)

        custom_tools: list[RunnableTool] = []
        for dotted in cfg.tools.custom:
            obj = import_dotted(dotted)
            custom_tools.append(obj)  # trusts the user's @tool-decorated callable

        registry = ToolRegistry()
        for t in (*artifact_tools, *search_tools, *custom_tools, *(tools or [])):
            # `RunnableTool` is structurally a `@tool`-decorated callable or a
            # `RunnableToolAdapter`; both are accepted by `register()`. Cast
            # at the boundary so mypy sees the union the registry expects.
            registry.register(t)  # type: ignore[arg-type]

        return cls(
            adapter=adapter,
            settings=cfg.settings,
            registry=registry,
            role=role_text,
            oracle_adapter=oracle_adapter,
        )

    def session(
        self,
        *,
        state: dict[str, object] | None = None,
        history: list[Turn] | None = None,
        session_id: str | None = None,
        profile: Profile = "full",
    ) -> Session:
        # `state` is reserved for user-attached metadata (e.g. {"user_id": "u1"}
        # per SPEC §4); persisted alongside the session by T-23.
        _ = state
        return Session(
            harness=self,
            session_id=session_id or uuid.uuid4().hex,
            parent_id=None,
            initial_history=list(history or []),
            profile=profile,
        )


class Session:
    """One conversation. Mutable. Forkable. Drives ``run_loop`` per query."""

    def __init__(
        self,
        *,
        harness: Harness,
        session_id: str,
        parent_id: str | None,
        initial_history: list[Turn],
        profile: Profile = "full",
    ) -> None:
        self.harness = harness
        self.id = session_id
        self.parent_id = parent_id
        self.profile: Profile = profile
        self._cache = ToolResultCache()
        s = harness.settings
        self._state = AgentState(
            session_id=session_id,
            role=harness.role,
            registry=harness.registry,
            profile=profile,
            adapter=harness.adapter,
            oracle_adapter=harness.oracle_adapter,
            max_iterations=s.max_iterations,
            context_budget_tokens=s.context_budget_tokens,
            max_session_notes=s.max_session_notes,
            history_keep_recent=s.history_keep_recent,
            nudge_interval=s.nudge_interval,
            max_consecutive_errors=s.max_consecutive_errors,
            compaction_thresholds=s.compaction_thresholds,
        )
        for turn in initial_history:
            self._state.append_turn(turn)
        self._events: list[Event] = []

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    async def run_stream(self, query: str) -> AsyncIterator[Event]:
        """Stream events for a single query to completion.

        Appends the user query as a Turn, then drives ``run_loop`` until it
        emits a terminal event. ``state.iterations`` is reset per call so
        ``max_iterations`` is a per-query budget, not a per-session one.
        """
        self._state.append_turn(Turn(role="user", content=query))
        s = self.harness.settings
        async for event in run_loop(
            self._state,
            session_id=self.id,
            cache=self._cache,
            default_char_limit=s.max_tool_result_chars,
            char_limits=s.tool_result_char_limits,
            seq_start=len(self._events),
        ):
            self._events.append(event)
            yield event

    async def run(self, query: str) -> FinalAnswerEvent:
        """Drain ``run_stream`` and return the final answer.

        One implementation, zero duplication with the streaming path. If the
        loop terminates without a ``FinalAnswerEvent`` (e.g. clarification or
        unrecoverable error), raises ``RuntimeError`` — the streaming API is
        the right tool for those cases.
        """
        final: FinalAnswerEvent | None = None
        async for event in self.run_stream(query):
            if isinstance(event, FinalAnswerEvent):
                final = event
        if final is None:
            raise RuntimeError(
                "loop ended without a FinalAnswerEvent; use run_stream() to "
                "observe clarification or error events"
            )
        return final

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------
    def history(self) -> list[Turn]:
        return list(self._state.history)

    def notes(self) -> list[Note]:
        return list(self._state.notes)

    def citations(self) -> list[Citation]:
        return list(self._state.citations)

    def events(self) -> list[Event]:
        return list(self._events)

    # ------------------------------------------------------------------
    # Forking
    # ------------------------------------------------------------------
    def fork(self, at_turn: int = -1) -> Session:
        """Branch from this session at ``at_turn``.

        ``at_turn=-1`` (default) forks from the current tail. Otherwise the
        new session inherits ``history[:at_turn]``. The fork gets a fresh
        cache and event log; ``parent_id`` points back to this session for
        the session tree (T-23).
        """
        history = list(self._state.history)
        if at_turn >= 0:
            history = history[:at_turn]
        return Session(
            harness=self.harness,
            session_id=uuid.uuid4().hex,
            parent_id=self.id,
            initial_history=history,
            profile=self.profile,
        )

    # ------------------------------------------------------------------
    # Stubs — land in later tasks
    # ------------------------------------------------------------------
    async def steer(self, message: str, mode: SteeringMode = "interrupt") -> None:
        """Enqueue a user steering message; consumed at the next loop boundary.

        SPEC §5.6. The wrapper is intentionally minimal: it delegates to
        ``AgentState.enqueue_steering`` so the loop's consumption point
        (``has_pending_steering`` / ``consume_steering`` — wired in T-06)
        stays the single source of truth.
        """
        self._state.enqueue_steering(message, mode)

    def save(self) -> None:
        raise NotImplementedError("session persistence lands with T-23")

    @classmethod
    def load(cls, session_id: str) -> Session:
        raise NotImplementedError("session persistence lands with T-23")


# ---------------------------------------------------------------------------
# Helpers — adapter resolution and role-file loading
# ---------------------------------------------------------------------------


def _build_adapter(provider: ProviderName, model: str) -> ModelAdapter:
    """Resolve a provider literal to a concrete adapter instance.

    Lazy-imports the per-provider module so users only pay for what they use.
    SDK absence surfaces as a clear :class:`ConfigError` rather than an opaque
    ``ImportError`` deep in adapter code.
    """
    try:
        if provider == "openai":
            from reigner.harness.adapters.openai import OpenAIAdapter

            return OpenAIAdapter(model=model)
        if provider == "anthropic":
            from reigner.harness.adapters.anthropic import AnthropicAdapter

            return AnthropicAdapter(model=model)
        if provider == "gemini":
            from reigner.harness.adapters.gemini import GeminiAdapter

            return GeminiAdapter(model=model)
    except ImportError as e:
        raise ConfigError(
            f"provider {provider!r} requires its optional dependency to be "
            f"installed (e.g. `uv add reigner[{provider}]`): {e}"
        ) from e

    raise ConfigError(f"unknown model provider: {provider!r}")


def _build_artifact_tools(cfg: ReignerConfig) -> list[RunnableTool]:
    """Resolve ``tools.artifacts`` to a fully built ArtifactStore tool list."""
    from reigner.artifacts import ArtifactSchema
    from reigner.tools.artifacts import ArtifactStore

    assert cfg.tools.artifacts is not None
    root = cfg.resolve(cfg.tools.artifacts.root)
    schema_path = cfg.resolve(cfg.tools.artifacts.schema_path)
    try:
        schema = ArtifactSchema.from_yaml(schema_path)
    except (OSError, ValueError) as exc:
        raise ConfigError(f"tools.artifacts: cannot load schema {schema_path}: {exc}") from exc
    store = ArtifactStore(root, schema)
    return list(store.tools())


def _build_search_tools(cfg: ReignerConfig) -> list[RunnableTool]:
    """Resolve ``tools.search`` to a built ``SearchIndex``'s tool list.

    Dispatches on ``cfg.tools.search.type``. Only ``"bm25"`` is known today;
    unknown values raise :class:`ConfigError` rather than silently no-op so
    typos surface at config-load time.
    """
    assert cfg.tools.search is not None
    index_path = cfg.resolve(cfg.tools.search.index_path)
    kind = cfg.tools.search.type
    if kind == "bm25":
        from reigner.tools.search import Bm25Index

        index = Bm25Index(index_path)
    else:
        raise ConfigError(f"tools.search.type={kind!r} is not supported (known: 'bm25')")
    return list(index.tools())


def _load_role(cfg: ReignerConfig) -> str:
    """Read ``cfg.role.file`` from disk, returning ``""`` if it's missing.

    Skill composition (T-30) layers on top of this string later; for T-17 we
    just slurp the file verbatim so a basic Harness has a usable role.
    """
    role_path = cfg.resolve(cfg.role.file)
    if not role_path.exists():
        return ""
    try:
        return role_path.read_text()
    except OSError as e:
        raise ConfigError(f"cannot read role file {role_path}: {e}") from e


__all__ = ["Harness", "Profile", "Session"]
