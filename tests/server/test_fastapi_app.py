"""Wire-contract tests for the FastAPI HTTP server (SPEC §16).

A scripted ``FakeAdapter`` (reused from ``tests/harness/test_loop``) keeps every
run offline and deterministic. Sessions are stored under a per-test ``tmp_path``
so resume/404 behaviour doesn't touch the developer's project. ``TestClient``
drives the ASGI app in-process and supports SSE via ``client.stream``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reigner.config import SettingsConfig
from reigner.harness.adapters.base import ModelAction
from reigner.harness.agent import Harness
from reigner.harness.events import from_json
from reigner.server.fastapi_app import create_app
from reigner.sessions.store import SessionStore
from tests.harness.test_loop import FakeAdapter, _final

AppBuilder = Callable[..., tuple[TestClient, Harness]]


@pytest.fixture
def make_app(tmp_path: Path) -> AppBuilder:
    """Build a TestClient over a harness whose session store is under tmp_path."""

    def _build(actions: list[ModelAction | Exception] | None = None) -> tuple[TestClient, Harness]:
        adapter = FakeAdapter(actions=list(actions if actions is not None else [_final("hi")]))
        harness = Harness(adapter=adapter, role="TEST", settings=SettingsConfig())
        harness.store = SessionStore(str(tmp_path / "sessions"))
        app = create_app(harness, name="test_agent", model="fake/fake-1")
        return TestClient(app), harness

    return _build


def _frames(raw: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event_name, json_data) pairs."""
    out: list[tuple[str, dict]] = []
    for block in raw.strip().split("\n\n"):
        if not block.strip():
            continue
        name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        out.append((name, json.loads(data)))
    return out


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health_reports_status_and_identity(make_app: AppBuilder) -> None:
    client, _ = make_app()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "name": "test_agent", "model": "fake/fake-1"}


# ---------------------------------------------------------------------------
# /run — happy paths
# ---------------------------------------------------------------------------


def test_run_streams_sse_with_final_answer(make_app: AppBuilder) -> None:
    client, _ = make_app([_final("the answer is 42")])
    resp = client.post("/run", json={"query": "what is the answer?"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    frames = _frames(resp.text)
    names = [name for name, _ in frames]
    # Each frame's event: line matches the payload's own type field.
    for name, data in frames:
        assert name == data["type"]
        assert from_json(json.dumps(data)) is not None
    assert names[0] == "user_query"
    assert names[-1] == "final_answer"
    assert frames[-1][1]["text"] == "the answer is 42"


def test_session_id_rides_every_frame(make_app: AppBuilder) -> None:
    client, _ = make_app([_final("done")])
    resp = client.post("/run", json={"query": "ping"})
    frames = _frames(resp.text)

    ids = {data["session_id"] for _, data in frames}
    assert len(ids) == 1  # one consistent id the client can resume with
    assert next(iter(ids))  # non-empty


def test_run_resumes_existing_session(make_app: AppBuilder) -> None:
    # First run mints + persists a session; capture its id from the stream.
    client, _ = make_app([_final("first"), _final("second")])
    first = client.post("/run", json={"query": "q1"})
    session_id = _frames(first.text)[0][1]["session_id"]

    # Second run resumes that id and streams again.
    resumed = client.post("/run", json={"query": "q2", "session_id": session_id})
    assert resumed.status_code == 200
    frames = _frames(resumed.text)
    assert all(data["session_id"] == session_id for _, data in frames)
    assert frames[-1][1]["text"] == "second"


# ---------------------------------------------------------------------------
# /run — error paths
# ---------------------------------------------------------------------------


def test_unknown_session_id_is_404(make_app: AppBuilder) -> None:
    client, _ = make_app()
    resp = client.post("/run", json={"query": "hi", "session_id": "does-not-exist"})
    assert resp.status_code == 404
    assert "does-not-exist" in resp.json()["detail"]


def test_empty_query_is_422(make_app: AppBuilder) -> None:
    client, _ = make_app()
    resp = client.post("/run", json={"query": ""})
    assert resp.status_code == 422


def test_bad_profile_is_422(make_app: AppBuilder) -> None:
    client, _ = make_app()
    resp = client.post("/run", json={"query": "hi", "profile": "superuser"})
    assert resp.status_code == 422


def test_mid_stream_failure_yields_terminal_error_frame(make_app: AppBuilder) -> None:
    # A plain exception escapes run_stream (the loop only wraps AdapterError),
    # so the SSE generator must convert it to a final error frame, not a 500.
    client, _ = make_app([RuntimeError("boom")])
    resp = client.post("/run", json={"query": "explode"})

    assert resp.status_code == 200  # headers already sent before the failure
    name, data = _frames(resp.text)[-1]
    assert name == "error"
    assert data["recoverable"] is False
    assert "boom" in data["error"]
