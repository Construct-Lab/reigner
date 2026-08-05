"""Optional FastAPI HTTP server — deploy a Reigner agent as a service.

Four endpoints over one shared, immutable :class:`Harness`:

- ``POST /run`` — stream the agent's event protocol as Server-Sent
  Events. An optional ``session_id`` resumes a durable session; absent, a new
  one is minted. The new/resumed id rides every frame (it's on the event
  envelope), so a client reads it off the first frame to continue later.
- ``GET /sessions`` — list every session in the store with its metadata.
- ``GET /sessions/{id}/events`` — replay one session's stored transcript, so a
  client that reloads can restore the thread instead of mirroring every event
  into a store of its own.
- ``GET /health`` — liveness + identity probe for load balancers and operators.

The server adds no new event types and owns no output path of its own: every
frame is ``to_json(event)``, the exact bytes the CLI's ``--json``
mode emits, just wrapped in SSE framing. The replay endpoint returns those same
envelopes as JSON. Build with :func:`create_app`; the ``serve`` CLI command
injects a live harness and the display strings for ``/health``.

**No auth, CORS, or rate limiting ships here** — that's deliberate scope, not an
oversight. Put a gateway in front before exposing this. Note that the read
endpoints raise the stakes of an accidental exposure: they serve every stored
transcript, not just the ability to ask a question.

Errors:

- Empty ``query`` / bad ``profile`` enum / ``limit`` below 1 → 422 from
  Pydantic, before any work.
- Unknown or malformed ``session_id`` → 404. Both collapse to 404 on purpose:
  an id that can't name a file isn't on disk either, and a uniform answer tells
  a prober nothing about the store's layout.
- An unreadable stored transcript (torn line, foreign JSONL) → 422.
- A failure *after* the stream opens (headers already sent, so no HTTP status
  is available) → a terminal ``error`` frame, then the stream closes. The loop
  already yields :class:`ErrorEvent` for adapter faults; this wraps anything
  that escapes ``run_stream`` so the client always sees a clean terminus.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from reigner.harness.agent import Harness, Session
from reigner.harness.events import ErrorEvent, Event, to_json
from reigner.sessions.store import InvalidSessionId, SessionStore
from reigner.types import Profile


class RunRequest(BaseModel):
    """Body of ``POST /run``.

    ``query`` is required and non-empty (empty → 422). ``session_id`` resumes a
    durable session when present; ``profile`` and ``state`` mirror the
    :meth:`Harness.session` knobs for *new* sessions — see the
    resume caveat on :func:`_resolve_session`.
    """

    query: str = Field(min_length=1)
    session_id: str | None = None
    profile: Profile = "full"
    state: dict[str, Any] = Field(default_factory=dict)


class SessionsResponse(BaseModel):
    """Body of ``GET /sessions`` — every session's stored metadata.

    ``sessions`` holds :class:`~reigner.sessions.store.SessionMeta` as plain
    dicts rather than a mirrored Pydantic model, so the payload can't drift from
    the dataclass. It's the same shape ``reigner session list --json`` emits.
    """

    sessions: list[dict[str, Any]]


class EventsResponse(BaseModel):
    """Body of ``GET /sessions/{id}/events`` — one session's transcript.

    ``events`` are the stored envelopes, in write order. They stay plain dicts
    for the same reason ``/run`` frames are raw ``to_json`` output: re-modelling
    them here would introduce a second schema that could silently disagree with
    the event protocol.

    ``total`` counts the whole transcript, not the returned window, so a client
    that passed ``limit`` can tell how much it didn't ask for; ``truncated``
    says whether it's looking at a suffix.
    """

    session_id: str
    total: int
    truncated: bool
    events: list[dict[str, Any]]


def _session_or_404(store: SessionStore, session_id: str) -> None:
    """Assert a session is readable, or raise 404.

    Unknown and structurally invalid ids both answer 404 — see the module
    docstring for why they're deliberately indistinguishable.

    Call this *before* reading. :meth:`SessionStore.load_events` is a generator,
    so its id validation only fires on the first ``next()`` — inside the read
    loop, where an :class:`InvalidSessionId` would be mistaken for a torn line
    and surface as a 422.
    """
    try:
        exists = store.exists(session_id)
    except InvalidSessionId:
        exists = False
    if not exists:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")


def _read_events(
    store: SessionStore, session_id: str, limit: int | None
) -> tuple[list[Event], int]:
    """Return ``(window, total)`` — the last ``limit`` events, in write order.

    A ``deque`` bounded by ``limit`` keeps the tail while the file streams past,
    so ``total`` stays honest on a long session without holding all of it in
    memory. ``limit=None`` returns everything.

    An unreadable row is a 422 rather than a skip: a transcript someone restores
    a conversation from is complete, or it's declared broken — never quietly
    short. The position reported counts events, not physical lines, since
    ``load_events`` drops blank ones.
    """
    window: deque[Event] | list[Event] = deque(maxlen=limit) if limit else []
    total = 0
    try:
        for event in store.load_events(session_id):
            window.append(event)
            total += 1
    except (ValueError, TypeError) as exc:
        # UnknownEventType, SchemaVersionMismatch and JSONDecodeError are all
        # ValueError; a row that parses but doesn't fit its event class raises
        # TypeError out of ``cls(**raw)``.
        raise HTTPException(
            status_code=422,
            detail=f"session {session_id!r} unreadable at event {total + 1}: {exc}",
        ) from exc
    return list(window), total


def _resolve_session(harness: Harness, req: RunRequest) -> Session:
    """New session, or resume an existing one — raising 404 if it's unknown.

    Resume goes through :meth:`Session.load`, which currently rebuilds at
    ``profile="full"`` regardless of ``req.profile``. So per-request
    tool gating only binds to *new* sessions; this is a documented v0 limit.
    """
    if req.session_id is None:
        return harness.session(state=req.state, profile=req.profile)
    _session_or_404(harness.store, req.session_id)
    return Session.load(req.session_id, harness=harness)


def _frame(event: Event) -> str:
    """Render one event as an SSE message: a named ``event:`` line + ``data:``.

    The type is also inside ``data`` (it's an event field), so a client can
    dispatch on either. Browsers can't use ``EventSource`` here — it only issues
    GETs and ``/run`` is a POST — so they call ``fetch()`` and parse the stream
    themselves; the ``event:`` line is there for the SSE tooling that does read
    it, and is safe to ignore.
    """
    return f"event: {event.type}\ndata: {to_json(event)}\n\n"


async def _sse(session: Session, query: str, request: Request) -> AsyncIterator[str]:
    """Drive one run, yielding SSE frames. Stop on disconnect; never raise out.

    A client hang-up (``is_disconnected``) ends the loop early so we don't burn
    model calls on an audience that left. Any exception escaping ``run_stream``
    becomes a terminal ``error`` frame — the HTTP status is already committed, so
    this is the only way to tell the client the run failed.
    """
    try:
        async for event in session.run_stream(query):
            if await request.is_disconnected():
                break
            yield _frame(event)
    except Exception as exc:  # noqa: BLE001 — headers sent; surface as a frame, not a 500
        err = ErrorEvent(
            seq=-1,
            session_id=session.id,
            turn=-1,
            error=f"{type(exc).__name__}: {exc}",
            recoverable=False,
        )
        yield _frame(err)


def create_app(harness: Harness, *, name: str, model: str) -> FastAPI:
    """Build the FastAPI app over a live harness.

    ``name`` and ``model`` are display strings for ``/health`` — the immutable
    :class:`Harness` doesn't retain them, so the caller (the ``serve`` command)
    reads them from ``reigner.yaml`` and passes them in. One harness is shared
    across all requests; each request gets its own :class:`Session`.
    """
    app = FastAPI(title=f"reigner · {name}")

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "name": name, "model": model})

    @app.post("/run")
    async def run(req: RunRequest, request: Request) -> StreamingResponse:
        session = _resolve_session(harness, req)
        return StreamingResponse(
            _sse(session, req.query, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/sessions")
    async def sessions() -> SessionsResponse:
        return SessionsResponse(sessions=[asdict(m) for m in harness.store.list()])

    @app.get("/sessions/{session_id}/events")
    async def session_events(
        session_id: str,
        limit: int | None = Query(
            None,
            ge=1,
            description="Return only the last N events. Omit for the whole transcript.",
        ),
    ) -> EventsResponse:
        _session_or_404(harness.store, session_id)
        window, total = _read_events(harness.store, session_id, limit)
        return EventsResponse(
            session_id=session_id,
            total=total,
            truncated=len(window) < total,
            events=[json.loads(to_json(e)) for e in window],
        )

    return app


__all__ = ["EventsResponse", "RunRequest", "SessionsResponse", "create_app"]
