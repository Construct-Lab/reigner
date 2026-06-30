"""Optional FastAPI HTTP server — deploy a Reigner agent as a service.

Two endpoints over one shared, immutable :class:`Harness`:

- ``POST /run`` — stream the agent's event protocol as Server-Sent
  Events. An optional ``session_id`` resumes a durable session; absent, a new
  one is minted. The new/resumed id rides every frame (it's on the event
  envelope), so a client reads it off the first frame to continue later.
- ``GET /health`` — liveness + identity probe for load balancers and operators.

The server adds no new event types and owns no output path of its own: every
frame is ``to_json(event)``, the exact bytes the CLI's ``--json``
mode emits, just wrapped in SSE framing. Build with :func:`create_app`; the
``serve`` CLI command injects a live harness and the display strings for
``/health``.

Errors:

- Empty ``query`` / bad ``profile`` enum → 422 from Pydantic, before any stream.
- Unknown ``session_id`` → 404, before any stream.
- A failure *after* the stream opens (headers already sent, so no HTTP status
  is available) → a terminal ``error`` frame, then the stream closes. The loop
  already yields :class:`ErrorEvent` for adapter faults; this wraps anything
  that escapes ``run_stream`` so the client always sees a clean terminus.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from reigner.harness.agent import Harness, Session
from reigner.harness.events import ErrorEvent, Event, to_json
from reigner.sessions.store import SessionNotFound
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


def _resolve_session(harness: Harness, req: RunRequest) -> Session:
    """New session, or resume an existing one — raising 404 if it's unknown.

    Resume goes through :meth:`Session.load`, which currently rebuilds at
    ``profile="full"`` regardless of ``req.profile``. So per-request
    tool gating only binds to *new* sessions; this is a documented v0 limit.
    """
    if req.session_id is None:
        return harness.session(state=req.state, profile=req.profile)
    try:
        return Session.load(req.session_id, harness=harness)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _frame(event: Event) -> str:
    """Render one event as an SSE message: a named ``event:`` line + ``data:``.

    The type is also inside ``data`` (it's an event field), so non-browser
    clients can ignore the ``event:`` line; browser ``EventSource`` clients can
    ``addEventListener(<type>, ...)``.
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

    return app


__all__ = ["RunRequest", "create_app"]
