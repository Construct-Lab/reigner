"""Session-level integration tests for the T-24 store wiring.

These tests drive the real loop via a scripted ``FakeAdapter`` (borrowed from
``tests/harness/test_loop.py``) to verify the end-to-end auto-save / resume /
fork / load behaviors that T-24 promises.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from reigner.config import SessionsConfig, SettingsConfig
from reigner.harness.agent import Harness, Session
from reigner.harness.events import Event, FinalAnswerEvent
from reigner.sessions.store import SessionNotFound, SessionStore
from tests.harness.test_loop import FakeAdapter, _final


def _build_harness(
    tmp_path: Path,
    *,
    auto_save: bool = True,
    actions: list[Any] | None = None,
) -> Harness:
    adapter = FakeAdapter(actions=list(actions or [_final("done")]))
    sessions = SessionsConfig(store_path=str(tmp_path / "sessions"), auto_save=auto_save)
    return Harness(
        adapter=adapter,
        settings=SettingsConfig(),
        sessions=sessions,
        role="ROLE",
    )


async def _drain(session: Session, query: str) -> list[Event]:
    return [ev async for ev in session.run_stream(query)]


# ---------------------------------------------------------------------------
# Harness wiring
# ---------------------------------------------------------------------------


def test_harness_builds_store_from_sessions_config(tmp_path: Path) -> None:
    h = _build_harness(tmp_path)
    assert isinstance(h.store, SessionStore)
    assert h.store.root == Path(h.sessions.store_path)


# ---------------------------------------------------------------------------
# Auto-save on / off
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_save_writes_event_per_yield(tmp_path: Path) -> None:
    h = _build_harness(tmp_path, actions=[_final("hi")])
    session = h.session()
    events = await _drain(session, "q?")

    assert len(events) == 1
    on_disk = list(h.store.load_events(session.id))
    assert len(on_disk) == 1
    assert isinstance(on_disk[0], FinalAnswerEvent)


@pytest.mark.asyncio
async def test_auto_save_off_stays_in_memory_until_save(tmp_path: Path) -> None:
    h = _build_harness(tmp_path, auto_save=False, actions=[_final("hi")])
    session = h.session()
    await _drain(session, "q?")

    assert not h.store.exists(session.id)
    session.save()
    assert h.store.exists(session.id)
    on_disk = list(h.store.load_events(session.id))
    assert len(on_disk) == 1


@pytest.mark.asyncio
async def test_meta_refreshed_after_run_stream(tmp_path: Path) -> None:
    h = _build_harness(tmp_path, actions=[_final("hi")])
    session = h.session()
    await _drain(session, "q?")

    meta = h.store.read_meta(session.id)
    assert meta.event_count == 1
    assert meta.session_id == session.id
    assert meta.parent_id is None


# ---------------------------------------------------------------------------
# set_title / save
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_title_persists_through_subsequent_writes(tmp_path: Path) -> None:
    h = _build_harness(tmp_path, actions=[_final("a"), _final("b")])
    session = h.session()
    await _drain(session, "q1")

    session.set_title("My title")
    assert h.store.read_meta(session.id).title == "My title"

    # Drive a second run; the meta refresh must not clobber title.
    await _drain(session, "q2")
    meta = h.store.read_meta(session.id)
    assert meta.title == "My title"
    assert meta.event_count == 2


# ---------------------------------------------------------------------------
# Resume across Sessions in the same Harness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_preloads_events_so_seq_continues(tmp_path: Path) -> None:
    h = _build_harness(tmp_path, actions=[_final("first"), _final("second")])
    sid = "resumeid"
    first = h.session(session_id=sid)
    await _drain(first, "q1")
    first_seqs = [ev.seq for ev in first.events()]

    # Build a fresh Session on the same id.
    resumed = h.session(session_id=sid)
    assert [ev.seq for ev in resumed.events()] == first_seqs

    await _drain(resumed, "q2")
    final_seqs = [ev.seq for ev in resumed.events()]
    assert final_seqs[: len(first_seqs)] == first_seqs
    # New events get fresh seq numbers continuing the sequence.
    assert final_seqs[len(first_seqs) :] == [len(first_seqs)]


# ---------------------------------------------------------------------------
# Fork
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_writes_parent_id_immediately(tmp_path: Path) -> None:
    h = _build_harness(tmp_path, actions=[_final("a")])
    parent = h.session()
    await _drain(parent, "q1")

    child = parent.fork()
    # Even though the child has no events yet, its meta exists with parent_id.
    meta = h.store.read_meta(child.id)
    assert meta.parent_id == parent.id
    assert meta.event_count == 0


# ---------------------------------------------------------------------------
# Session.load — inspection-only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_load_returns_inspection_only(tmp_path: Path) -> None:
    h = _build_harness(tmp_path, actions=[_final("hi")])
    original = h.session()
    await _drain(original, "q?")
    original_events = original.events()

    loaded = Session.load(original.id, harness=h)
    assert loaded.id == original.id
    assert loaded.parent_id == original.parent_id
    assert [ev.seq for ev in loaded.events()] == [ev.seq for ev in original_events]

    with pytest.raises(NotImplementedError):
        async for _ in loaded.run_stream("can't run this"):
            pass


def test_session_load_missing_id_raises(tmp_path: Path) -> None:
    h = _build_harness(tmp_path)
    with pytest.raises(SessionNotFound):
        Session.load("never-existed", harness=h)


# ---------------------------------------------------------------------------
# Export / import via Harness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_export_then_import_preserves_link(tmp_path: Path) -> None:
    h = _build_harness(tmp_path, actions=[_final("a")])
    sid = "parentid"
    parent = h.session(session_id=sid)
    await _drain(parent, "q?")

    bundle = tmp_path / "out" / "session.jsonl"
    parent.export(bundle)

    # Fresh harness pointing at a different store dir.
    h2 = _build_harness(tmp_path / "scratch", actions=[_final("b")])
    imported = h2.import_session(bundle)
    assert imported.id == sid
    assert imported.parent_id == parent.parent_id
    assert [ev.seq for ev in imported.events()] == [ev.seq for ev in parent.events()]
    # Imported sessions are inspection-only.
    with pytest.raises(NotImplementedError):
        async for _ in imported.run_stream("nope"):
            pass
