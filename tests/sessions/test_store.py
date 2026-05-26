"""Unit tests for :class:`SessionStore` (T-24)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reigner.harness.events import (
    SCHEMA_VERSION,
    FinalAnswerEvent,
    SchemaVersionMismatch,
    StatusEvent,
    ToolCallEvent,
    UnknownEventType,
)
from reigner.sessions.store import (
    InvalidSessionId,
    SessionMeta,
    SessionNotFound,
    SessionStore,
)


def _status(sid: str, seq: int, turn: int = 0, msg: str = "hi") -> StatusEvent:
    return StatusEvent(seq=seq, session_id=sid, turn=turn, message=msg)


def _final(sid: str, seq: int, turn: int = 1) -> FinalAnswerEvent:
    return FinalAnswerEvent(seq=seq, session_id=sid, turn=turn, text="answer", metadata={})


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def test_append_then_load_returns_events_in_order(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid = "abc123"
    store.append_event(sid, _status(sid, 0, msg="first"))
    store.append_event(sid, _status(sid, 1, msg="second"))
    store.append_event(sid, _final(sid, 2))

    loaded = list(store.load_events(sid))

    assert len(loaded) == 3
    assert [e.seq for e in loaded] == [0, 1, 2]
    assert isinstance(loaded[-1], FinalAnswerEvent)


def test_load_events_skips_blank_lines(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid = "abc123"
    store.append_event(sid, _status(sid, 0))
    # Manually inject a blank line; the loader should ignore it.
    with (tmp_path / f"{sid}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("\n")
    store.append_event(sid, _status(sid, 1))

    loaded = list(store.load_events(sid))
    assert len(loaded) == 2


def test_load_events_raises_when_session_missing(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    with pytest.raises(SessionNotFound):
        list(store.load_events("nope"))


# ---------------------------------------------------------------------------
# Resume across instances
# ---------------------------------------------------------------------------


def test_resume_across_store_instances_appends(tmp_path: Path) -> None:
    sid = "abc123"
    SessionStore(tmp_path).append_event(sid, _status(sid, 0, msg="from-a"))
    SessionStore(tmp_path).append_event(sid, _status(sid, 1, msg="from-b"))

    loaded = list(SessionStore(tmp_path).load_events(sid))
    messages = [e.message for e in loaded if isinstance(e, StatusEvent)]
    assert messages == ["from-a", "from-b"]


# ---------------------------------------------------------------------------
# session_id validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        "",
        "../etc",
        "foo/bar",
        "foo\\bar",
        "with space",
        "with.dot",
        "weird*",
    ],
)
def test_invalid_session_id_rejected(tmp_path: Path, bad_id: str) -> None:
    store = SessionStore(tmp_path)
    with pytest.raises(InvalidSessionId):
        store.append_event(bad_id, _status("safe", 0))


def test_valid_session_id_accepted(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    # UUID-style hex, kebab-case, snake_case all permitted.
    for sid in ("abcdef0123", "kebab-case-id", "snake_case_id", "A1B2"):
        store.append_event(sid, _status(sid, 0))
        assert store.exists(sid)


# ---------------------------------------------------------------------------
# meta.json
# ---------------------------------------------------------------------------


def test_read_meta_rebuilds_when_sidecar_missing(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid = "abc123"
    store.append_event(sid, _status(sid, 0))
    store.append_event(sid, _final(sid, 1))

    # No write_meta yet — sidecar absent.
    assert not (tmp_path / f"{sid}.meta.json").exists()
    meta = store.read_meta(sid)

    assert meta.session_id == sid
    assert meta.event_count == 2
    assert meta.parent_id is None
    assert meta.title is None
    assert meta.schema_version == SCHEMA_VERSION


def test_write_meta_then_read_meta_round_trip(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid = "abc123"
    store.append_event(sid, _status(sid, 0))
    meta = SessionMeta(
        session_id=sid,
        parent_id="parent000",
        title="My session",
        event_count=1,
    )
    store.write_meta(sid, meta)

    again = store.read_meta(sid)
    assert again.session_id == sid
    assert again.parent_id == "parent000"
    assert again.title == "My session"
    assert again.event_count == 1


def test_write_meta_id_mismatch_rejected(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    meta = SessionMeta(session_id="other")
    with pytest.raises(ValueError):
        store.write_meta("abc123", meta)


def test_set_title_updates_only_title(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid = "abc123"
    store.append_event(sid, _status(sid, 0))
    meta = store.read_meta(sid)
    store.write_meta(sid, meta)

    updated = store.set_title(sid, "Apple R&D 2024")
    assert updated.title == "Apple R&D 2024"
    assert store.read_meta(sid).title == "Apple R&D 2024"
    # event_count is preserved
    assert updated.event_count == meta.event_count


def test_schema_version_mismatch_on_read(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid = "abc123"
    store.append_event(sid, _status(sid, 0))
    # Tamper with the sidecar
    meta_path = tmp_path / f"{sid}.meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "session_id": sid,
                "parent_id": None,
                "title": None,
                "created": "2026-05-23T00:00:00+00:00",
                "last_updated": "2026-05-23T00:00:00+00:00",
                "event_count": 1,
                "schema_version": 999,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SchemaVersionMismatch):
        store.read_meta(sid)


def test_v1_meta_remains_visible_for_tree_and_inspection(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid = "legacy"
    store.append_event(sid, _status(sid, 0))
    (tmp_path / f"{sid}.meta.json").write_text(
        json.dumps(
            {
                "session_id": sid,
                "parent_id": None,
                "title": "old transcript",
                "created": "2026-05-23T00:00:00+00:00",
                "last_updated": "2026-05-23T00:00:00+00:00",
                "event_count": 1,
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )

    meta = store.read_meta(sid)

    assert meta.title == "old transcript"
    assert meta.schema_version == SCHEMA_VERSION
    assert [listed.session_id for listed in store.list()] == [sid]


# ---------------------------------------------------------------------------
# list / exists
# ---------------------------------------------------------------------------


def test_list_returns_sorted_metas(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    for sid in ("ccc", "aaa", "bbb"):
        store.append_event(sid, _status(sid, 0))
    metas = store.list()
    assert [m.session_id for m in metas] == ["aaa", "bbb", "ccc"]


def test_list_skips_broken_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.append_event("good", _status("good", 0))
    # Plant a stale-schema meta sidecar that read_meta will refuse.
    (tmp_path / "bad.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "bad.meta.json").write_text(
        json.dumps({"session_id": "bad", "schema_version": 999}), encoding="utf-8"
    )
    metas = store.list()
    assert [m.session_id for m in metas] == ["good"]


def test_list_on_empty_root_returns_empty(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "nonexistent")
    assert store.list() == []


def test_exists_true_after_append(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    assert not store.exists("abc")
    store.append_event("abc", _status("abc", 0))
    assert store.exists("abc")


# ---------------------------------------------------------------------------
# Export / import
# ---------------------------------------------------------------------------


def test_export_writes_jsonl_and_sidecar(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "store")
    sid = "abc123"
    store.append_event(sid, _status(sid, 0))
    store.write_meta(
        sid,
        SessionMeta(session_id=sid, parent_id="parent00", title="exported", event_count=1),
    )

    out = tmp_path / "out" / "session.jsonl"
    returned = store.export(sid, out)

    assert returned == out
    assert out.exists()
    sidecar = out.with_suffix(".meta.json")
    assert sidecar.exists()
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["session_id"] == sid
    assert meta["parent_id"] == "parent00"
    assert meta["title"] == "exported"


def test_import_round_trip_preserves_parent_id(tmp_path: Path) -> None:
    source = SessionStore(tmp_path / "src")
    sid = "abc123"
    source.append_event(sid, _status(sid, 0))
    source.append_event(sid, _final(sid, 1))
    source.write_meta(
        sid,
        SessionMeta(
            session_id=sid,
            parent_id="parent00",
            title="exported",
            event_count=2,
        ),
    )
    bundle = tmp_path / "bundle" / "session.jsonl"
    source.export(sid, bundle)

    dest = SessionStore(tmp_path / "dst")
    imported_sid = dest.import_(bundle)

    assert imported_sid == sid
    assert dest.exists(sid)
    meta = dest.read_meta(sid)
    assert meta.parent_id == "parent00"
    assert meta.title == "exported"
    assert [e.seq for e in dest.load_events(sid)] == [0, 1]


def test_import_without_sidecar_uses_first_event_session_id(tmp_path: Path) -> None:
    sid = "abc123"
    bundle = tmp_path / "session.jsonl"
    # Hand-write a JSONL without an accompanying sidecar.
    from reigner.harness.events import to_json

    with bundle.open("w", encoding="utf-8") as fh:
        fh.write(to_json(_status(sid, 0)) + "\n")
        fh.write(to_json(_final(sid, 1)) + "\n")

    dest = SessionStore(tmp_path / "dst")
    imported_sid = dest.import_(bundle)

    assert imported_sid == sid
    rebuilt = dest.read_meta(sid)
    assert rebuilt.event_count == 2
    assert rebuilt.parent_id is None  # unrecoverable from events alone


def test_import_collision_raises(tmp_path: Path) -> None:
    source = SessionStore(tmp_path / "src")
    sid = "abc123"
    source.append_event(sid, _status(sid, 0))
    source.write_meta(sid, SessionMeta(session_id=sid, event_count=1))
    bundle = tmp_path / "session.jsonl"
    source.export(sid, bundle)

    dest = SessionStore(tmp_path / "dst")
    dest.append_event(sid, _status(sid, 0))  # collision waiting to happen

    with pytest.raises(FileExistsError):
        dest.import_(bundle)


def test_import_missing_source_raises(tmp_path: Path) -> None:
    dest = SessionStore(tmp_path / "dst")
    with pytest.raises(FileNotFoundError):
        dest.import_(tmp_path / "missing.jsonl")


def test_export_missing_session_raises(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    with pytest.raises(SessionNotFound):
        store.export("abc", tmp_path / "out.jsonl")


# ---------------------------------------------------------------------------
# Unknown event types
# ---------------------------------------------------------------------------


def test_load_events_propagates_unknown_event_type(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid = "abc123"
    store.append_event(sid, _status(sid, 0))
    # Inject a line with a bogus type.
    with (tmp_path / f"{sid}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "no_such_event", "seq": 1}) + "\n")
    with pytest.raises(UnknownEventType):
        list(store.load_events(sid))


# ---------------------------------------------------------------------------
# Round-trip of complex tool event
# ---------------------------------------------------------------------------


def test_round_trip_tool_call_event(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid = "abc123"
    ev = ToolCallEvent(
        seq=0,
        session_id=sid,
        turn=1,
        name="grep",
        args={"pattern": "foo", "limit": 10},
        call_id="call-1",
    )
    store.append_event(sid, ev)
    [loaded] = list(store.load_events(sid))
    assert isinstance(loaded, ToolCallEvent)
    assert loaded.name == "grep"
    assert loaded.args == {"pattern": "foo", "limit": 10}
    assert loaded.call_id == "call-1"
