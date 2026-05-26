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
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from reigner.config import ReignerConfig, SessionsConfig, SettingsConfig
from reigner.harness.adapters.base import ModelAdapter
from reigner.harness.cache import ToolResultCache
from reigner.harness.events import Event, FinalAnswerEvent, UserQueryEvent
from reigner.harness.loop import RunnableTool, run_loop
from reigner.harness.state import AgentState, Citation, Note, SteeringMode, Turn
from reigner.plugins.host import PluginHost
from reigner.plugins.registry import load_plugins
from reigner.sessions.replay import reconstruct, round_boundaries
from reigner.sessions.store import SessionMeta, SessionNotFound, SessionStore
from reigner.tools.provenance import register_citation
from reigner.tools.pseudo import (
    escalate_to_oracle,
    request_clarification,
    save_note,
    stop,
)
from reigner.tools.registry import ToolRegistry
from reigner.types import ConfigError, Profile, ProviderName, import_dotted

if TYPE_CHECKING:
    pass


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(kw_only=True)
class Harness:
    """Immutable configured agent. Build once, spawn many sessions.

    All loop budgets live on :attr:`settings`. Construct a custom
    :class:`SettingsConfig` and pass it in to override defaults — or pass
    nothing and ride the defaults from SPEC §13.
    """

    adapter: ModelAdapter
    settings: SettingsConfig = field(default_factory=SettingsConfig)
    sessions: SessionsConfig = field(default_factory=SessionsConfig)
    registry: ToolRegistry = field(default_factory=ToolRegistry)
    role: str = ""
    oracle_adapter: ModelAdapter | None = None
    plugins: PluginHost = field(default_factory=PluginHost.empty)
    store: SessionStore = field(init=False)
    """Built from :attr:`sessions.store_path` in :meth:`__post_init__`.

    Override after construction (``h.store = SessionStore(elsewhere)``) for
    tests that need a custom path; production callers should configure
    :attr:`sessions` instead.
    """

    def __post_init__(self) -> None:
        self.store = SessionStore(self.sessions.store_path)

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
        - ``tools.fs`` is wired to :class:`reigner.tools.fs.FsTools` — the
          raw filesystem surface (SPEC §6.4 FS tools). Off by default; only
          registered when ``tools.fs`` is present in the config.
        - Plugins (``cfg.plugins``) are resolved to a :class:`PluginHost` whose
          hooks fire around the loop (SPEC §12).
        - Sessions / eval sections parse but the runtime that consumes them
          isn't on Harness yet.

        Tool wiring order: ``[builtin tools, artifact tools, search tools,
        fs tools, custom tools, *(tools or [])]``. Builtins (SPEC §6.4 pseudo-tools +
        :func:`register_citation` from SPEC §1 principle 4) are auto-registered
        first so any user tool that collides on name raises loudly rather than
        silently shadowing a control verb. ``escalate_to_oracle`` is only
        registered when ``cfg.oracle`` is set — registering it without an oracle
        adapter would let the model invoke a verb that faults at dispatch time.
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
            artifact_tools = build_artifact_tools(cfg)

        search_tools: list[RunnableTool] = []
        if cfg.tools.search is not None:
            search_tools = build_search_tools(cfg)

        fs_tools: list[RunnableTool] = []
        if cfg.tools.fs is not None:
            fs_tools = build_fs_tools(cfg)

        custom_tools: list[RunnableTool] = []
        for dotted in cfg.tools.custom:
            obj = import_dotted(dotted)
            custom_tools.append(obj)  # trusts the user's @tool-decorated callable

        # The @tool decorator returns the original callable unchanged (with a
        # `__reigner_spec__` attached), so mypy sees plain async callables here;
        # the registry accepts them structurally. Cast at the boundary.
        builtin_tools: list[RunnableTool] = [
            save_note,  # type: ignore[list-item]
            request_clarification,  # type: ignore[list-item]
            stop,  # type: ignore[list-item]
            register_citation,  # type: ignore[list-item]
        ]
        if oracle_adapter is not None:
            builtin_tools.append(escalate_to_oracle)  # type: ignore[arg-type]

        registry = ToolRegistry()
        for t in (
            *builtin_tools,
            *artifact_tools,
            *search_tools,
            *fs_tools,
            *custom_tools,
            *(tools or []),
        ):
            # `RunnableTool` is structurally a `@tool`-decorated callable or a
            # `RunnableToolAdapter`; both are accepted by `register()`. Cast
            # at the boundary so mypy sees the union the registry expects.
            registry.register(t)  # type: ignore[arg-type]

        resolved_sessions = SessionsConfig(
            store_path=str(cfg.resolve(cfg.sessions.store_path)),
            auto_save=cfg.sessions.auto_save,
        )

        return cls(
            adapter=adapter,
            settings=cfg.settings,
            sessions=resolved_sessions,
            registry=registry,
            role=role_text,
            oracle_adapter=oracle_adapter,
            plugins=PluginHost(load_plugins(cfg.plugins)),
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
        resolved_id = session_id or uuid.uuid4().hex
        parent_id = (
            self.store.read_meta(resolved_id).parent_id
            if session_id is not None and self.store.exists(resolved_id)
            else None
        )
        return Session(
            harness=self,
            session_id=resolved_id,
            parent_id=parent_id,
            initial_history=list(history or []),
            profile=profile,
        )

    def import_session(self, src_path: str | Path) -> Session:
        """Import an exported session JSONL into the store, then load it.

        The returned :class:`Session` is fully live — its state is reconstructed
        from the imported log (T-25), so ``run_stream``/``fork``/``replay`` work.
        """
        sid = self.store.import_(src_path)
        return Session.load(sid, harness=self)


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
        # Resume: if a session by this id is already on disk, preload its events
        # (so seq numbering continues) and reconstruct in-memory state from the
        # log so the conversation continues from where it left off (T-25).
        if harness.store.exists(session_id):
            self._events.extend(harness.store.load_events(session_id))
            if self._events:
                self._seed_state(
                    reconstruct(
                        self._events,
                        settings=harness.settings,
                        session_id=session_id,
                        role=harness.role,
                    )
                )
        self._persisted_count = len(self._events)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    async def run_stream(self, query: str) -> AsyncIterator[Event]:
        """Stream events for a single query to completion.

        Emits a ``UserQueryEvent`` (so the query is durable — reconstruction in
        T-25 depends on it and uses it as the round boundary), appends the query
        as a Turn, then drives ``run_loop`` until it emits a terminal event.
        ``state.iterations`` is reset per call so ``max_iterations`` is a
        per-query budget, not a per-session one.

        Auto-saves each event to the session store when
        ``harness.sessions.auto_save`` is true (the default); the meta sidecar
        is refreshed once the stream completes.
        """
        s = self.harness.settings
        auto_save = self.harness.sessions.auto_save
        store = self.harness.store

        # Record the query first — emitted, persisted, and yielded — so the
        # event log is a complete transcript. The loop never sees the raw
        # query as an event, so this is the only place it gets logged.
        query_event = UserQueryEvent(
            seq=len(self._events),
            session_id=self.id,
            turn=0,
            query=query,
        )
        self._events.append(query_event)
        if auto_save:
            store.append_event(self.id, query_event)
            self._persisted_count += 1
        yield query_event

        self._state.append_turn(Turn(role="user", content=query))
        try:
            async for event in run_loop(
                self._state,
                session_id=self.id,
                cache=self._cache,
                default_char_limit=s.max_tool_result_chars,
                char_limits=s.tool_result_char_limits,
                seq_start=len(self._events),
                plugins=self.harness.plugins,
            ):
                self._events.append(event)
                if auto_save:
                    store.append_event(self.id, event)
                    self._persisted_count += 1
                yield event
        finally:
            if auto_save:
                store.write_meta(self.id, self._build_meta(store))

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
        """Branch a new session from this one at conversational round ``at_turn``.

        ``at_turn`` counts conversational rounds (``UserQueryEvent`` boundaries),
        1-based. ``fork(at_turn=N)`` keeps rounds ``1..N-1`` and leaves the child
        ready to accept new input; ``at_turn=-1`` (default) forks from the tail
        (every round). The child's JSONL is a self-contained snapshot — the
        parent's event prefix is copied in with ``session_id`` rewritten — so the
        branch can be reconstructed, replayed, and diffed on its own.
        ``parent_id`` points back to this session for the fork tree.
        """
        events = list(self._events)
        cut = self._cut_index(events, at_turn)
        child_id = uuid.uuid4().hex
        prefix = [replace(ev, session_id=child_id) for ev in events[:cut]]

        child = Session(
            harness=self.harness,
            session_id=child_id,
            parent_id=self.id,
            initial_history=[],
            profile=self.profile,
        )
        # __init__ saw no file for the fresh id, so child state is empty; rebuild
        # it from the prefix we're about to adopt.
        if prefix:
            child._seed_state(
                reconstruct(
                    prefix,
                    settings=self.harness.settings,
                    session_id=child_id,
                    role=self.harness.role,
                )
            )
        child._events = prefix

        store = self.harness.store
        if self.harness.sessions.auto_save:
            # Persist an empty JSONL for fork(at_turn=1) as well: a branch with
            # no copied rounds must still be loadable and appear in the tree.
            store.write_session_events(child_id, prefix)
            child._persisted_count = len(prefix)
            store.write_meta(child_id, child._build_meta(store))
        return child

    async def replay(self, at_turn: int) -> Session:
        """Re-run round ``at_turn`` live, returning a new child session.

        SPEC §11.2. Forks at round ``at_turn`` (keeping rounds ``1..N-1``), then
        re-issues that round's *recorded* query against this Harness's current
        model & ROLE and runs it to completion on the child. This session is
        untouched, so the original answer stays diff-able against the new branch
        (acceptance criterion #6). To compare models, load the session into a
        Harness configured with the other model and call ``replay`` there.
        """
        bounds = round_boundaries(self._events)
        if at_turn < 1 or at_turn > len(bounds):
            raise ValueError(
                f"at_turn={at_turn} out of range — session has {len(bounds)} recorded round(s)"
            )
        query = cast("UserQueryEvent", self._events[bounds[at_turn - 1]]).query
        child = self.fork(at_turn=at_turn)
        async for _ in child.run_stream(query):
            pass
        return child

    def _cut_index(self, events: list[Event], at_turn: int) -> int:
        """Translate a 1-based round ``at_turn`` (or ``-1`` tail) into an event-list cut.

        Returns the index such that ``events[:cut]`` is rounds ``1..at_turn-1``.
        """
        if at_turn == -1:
            return len(events)
        if at_turn < 1:
            raise ValueError("at_turn must be >= 1 (1-based round) or -1 for the tail")
        bounds = round_boundaries(events)
        if at_turn > len(bounds):
            raise ValueError(
                f"at_turn={at_turn} exceeds the {len(bounds)} recorded round(s) in this session"
            )
        return bounds[at_turn - 1]

    def _seed_state(self, src: AgentState) -> None:
        """Adopt reconstructed history/notes/citations into this session's live state.

        ``src`` comes from :func:`reconstruct` and carries stub tooling; we copy
        only the conversational payload, leaving this session's real registry,
        adapter, and budgets intact so it can keep running.
        """
        self._state.history = list(src.history)
        self._state.notes = list(src.notes)
        self._state.citations = list(src.citations)

    # ------------------------------------------------------------------
    # Steering
    # ------------------------------------------------------------------
    async def steer(self, message: str, mode: SteeringMode = "interrupt") -> None:
        """Enqueue a user steering message; consumed at the next loop boundary.

        SPEC §5.6. The wrapper is intentionally minimal: it delegates to
        ``AgentState.enqueue_steering`` so the loop's consumption point
        (``has_pending_steering`` / ``consume_steering`` — wired in T-06)
        stays the single source of truth.
        """
        self._state.enqueue_steering(message, mode)

    # ------------------------------------------------------------------
    # Persistence (T-24)
    # ------------------------------------------------------------------
    def save(self) -> SessionMeta:
        """Flush any unpersisted events plus the meta sidecar to disk.

        Events are already on disk after each ``run_stream`` yield when
        ``auto_save`` is true; this method matters for sessions running with
        ``auto_save=False``, and as an explicit checkpoint for the meta
        sidecar (which is otherwise written lazily). Returns the meta that
        was written.
        """
        store = self.harness.store
        for event in self._events[self._persisted_count :]:
            store.append_event(self.id, event)
            self._persisted_count += 1
        if not store.exists(self.id):
            store.write_session_events(self.id, [])
        meta = self._build_meta(store)
        store.write_meta(self.id, meta)
        return meta

    def set_title(self, title: str | None) -> SessionMeta:
        """Set or clear the session title in the meta sidecar."""
        return self.harness.store.set_title(self.id, title)

    def export(self, dest_path: str | Path) -> Path:
        """Write this session's JSONL (plus sidecar meta) to ``dest_path``."""
        return self.harness.store.export(self.id, dest_path)

    @classmethod
    def load(cls, session_id: str, *, harness: Harness) -> Session:
        """Load a stored session, reconstructing its state so it can be resumed.

        Reads the meta sidecar for ``parent_id``, preloads the event log, and
        rebuilds history/notes/citations via deterministic replay (T-25). The
        returned session is fully live: ``run_stream``, ``fork``, and ``replay``
        all work. Raises :class:`SessionNotFound` if the id isn't on disk, or
        :class:`reigner.sessions.replay.ReplayError` if the log predates
        ``UserQueryEvent`` (SCHEMA_VERSION 1) and carries no recorded query.
        """
        store = harness.store
        if not store.exists(session_id):
            raise SessionNotFound(f"session {session_id!r} not found at {store.root}")
        meta = store.read_meta(session_id)
        return cls(
            harness=harness,
            session_id=session_id,
            parent_id=meta.parent_id,
            initial_history=[],
            profile="full",
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _build_meta(self, store: SessionStore) -> SessionMeta:
        """Build the meta record to persist, preserving ``created`` / ``title``.

        Reads the existing sidecar (if any) so we don't clobber user-set
        fields like ``title`` or the original ``created`` timestamp on every
        write.
        """
        existing: SessionMeta | None = None
        if store.exists(self.id):
            try:
                existing = store.read_meta(self.id)
            except SessionNotFound:
                existing = None
        return SessionMeta(
            session_id=self.id,
            parent_id=self.parent_id,
            title=existing.title if existing else None,
            created=existing.created if existing else _utcnow_iso(),
            last_updated=_utcnow_iso(),
            event_count=len(self._events),
        )


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


def build_artifact_tools(cfg: ReignerConfig) -> list[RunnableTool]:
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


def build_search_tools(cfg: ReignerConfig) -> list[RunnableTool]:
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


def build_fs_tools(cfg: ReignerConfig) -> list[RunnableTool]:
    """Resolve ``tools.fs`` to a built :class:`FsTools`' tool list.

    Mirrors :func:`build_artifact_tools` / :func:`build_search_tools` so the
    CLI's ``reigner inspect tools`` and the harness use the same construction
    path.
    """
    from reigner.tools.fs import FsTools

    assert cfg.tools.fs is not None
    root = cfg.resolve(cfg.tools.fs.root)
    fs = FsTools(root, write_enabled=cfg.tools.fs.write_enabled)
    return list(fs.tools())


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
