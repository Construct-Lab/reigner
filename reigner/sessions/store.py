"""Session store — durable JSONL persistence for agent conversations.

SPEC.md §11. Sessions are durable, forkable, branchable JSON files on disk.
This module owns the disk format and the data layer; :class:`Session` wiring
lives in :mod:`reigner.harness.agent`. Reconstruction and fork-tree navigation
live in :mod:`reigner.sessions.replay` and :mod:`reigner.sessions.tree`.

On-disk layout
--------------
``{root}/{session_id}.jsonl``       — one JSON line per event, via :func:`events.to_json`.
``{root}/{session_id}.meta.json``   — summary sidecar: title, parent_id, counts, schema.

The store is single-writer per ``session_id`` by convention. Two processes
writing the same id will interleave appended lines; v0 takes no locks.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from reigner.harness import events
from reigner.harness.events import SCHEMA_VERSION, Event, SchemaVersionMismatch


class SessionNotFound(FileNotFoundError):
    """Raised when a session id has no JSONL file under the store root."""


class InvalidSessionId(ValueError):
    """Raised when a session id contains characters that aren't filename-safe."""


# Permissive enough for UUID hex, kebab-case, and user-chosen ids; strict
# enough to reject path separators, dots, whitespace, and shell metacharacters.
_VALID_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(kw_only=True)
class SessionMeta:
    """Summary record for one session, persisted as ``{sid}.meta.json``.

    ``total_tokens`` and ``total_cost`` are deliberately absent — no event
    carries them yet. They'll be added as fields when later tasks emit usage
    events; the ``schema_version`` bumps in lockstep so old sessions still
    load via a migration path.
    """

    session_id: str
    parent_id: str | None = None
    title: str | None = None
    created: str = field(default_factory=_utcnow_iso)
    last_updated: str = field(default_factory=_utcnow_iso)
    event_count: int = 0
    schema_version: int = SCHEMA_VERSION

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=False)

    @classmethod
    def from_json(cls, raw: str) -> SessionMeta:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("meta.json must be a JSON object")
        version = data.get("schema_version")
        if version == 1:
            # T-25 changes the event transcript (query rows), not the metadata
            # fields. Preserve v1 visibility for list/tree/inspection; state
            # reconstruction still rejects v1 logs without UserQueryEvent.
            data["schema_version"] = SCHEMA_VERSION
            return cls(**data)
        if version != SCHEMA_VERSION:
            raise SchemaVersionMismatch(
                f"session meta schema_version {version!r} != expected {SCHEMA_VERSION}"
            )
        return cls(**data)


class SessionStore:
    """Filesystem-backed store of session JSONL + meta sidecars.

    One :class:`SessionStore` is owned by a :class:`Harness`; every
    :class:`Session` shares it. The store doesn't cache file handles — each
    :meth:`append_event` opens, writes, flushes, closes. Crash-safe per event
    at the cost of one open per event; that's the trade we want for an
    artifact you debug after the fact.
    """

    def __init__(self, root_path: str | Path) -> None:
        self._root = Path(root_path)

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # ID / path helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_id(session_id: str) -> None:
        if not isinstance(session_id, str) or not session_id:
            raise InvalidSessionId("session_id must be a non-empty string")
        if not _VALID_ID.match(session_id):
            raise InvalidSessionId(
                f"session_id {session_id!r} must match {_VALID_ID.pattern}; "
                "no path separators, dots, or whitespace permitted"
            )

    def _jsonl_path(self, session_id: str) -> Path:
        self._validate_id(session_id)
        return self._root / f"{session_id}.jsonl"

    def _meta_path(self, session_id: str) -> Path:
        self._validate_id(session_id)
        return self._root / f"{session_id}.meta.json"

    def _ensure_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def exists(self, session_id: str) -> bool:
        return self._jsonl_path(session_id).exists()

    def list(self) -> list[SessionMeta]:
        """Return meta for every session under the root, sorted by id.

        Malformed sessions (unreadable JSONL, version mismatch) are skipped
        so a single broken file doesn't poison the listing.
        """
        if not self._root.exists():
            return []
        out: list[SessionMeta] = []
        for jsonl in sorted(self._root.glob("*.jsonl")):
            sid = jsonl.stem
            try:
                out.append(self.read_meta(sid))
            except (SchemaVersionMismatch, OSError, ValueError):
                continue
        return out

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def append_event(self, session_id: str, event: Event) -> None:
        """Serialize ``event`` and append it as one line to ``{sid}.jsonl``.

        Flushes after each write so a crash mid-conversation loses at most
        the in-flight event. Meta is not touched here — call :meth:`write_meta`
        when summary fields need refreshing.
        """
        path = self._jsonl_path(session_id)
        line = events.to_json(event)
        self._ensure_root()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.write("\n")
            fh.flush()

    def write_session_events(self, session_id: str, event_list: Iterable[Event]) -> int:
        """Write ``event_list`` as the complete JSONL for ``session_id`` (overwrites).

        Used by :meth:`Session.fork` to snapshot a parent's event prefix into a
        fresh child file. The caller owns ``session_id`` consistency — events
        whose ``session_id`` field doesn't match are written as-is, so rewrite
        them (``dataclasses.replace``) before calling if a self-contained
        transcript is wanted. Returns the number of events written.
        """
        self._validate_id(session_id)
        self._ensure_root()
        path = self._jsonl_path(session_id)
        count = 0
        with path.open("w", encoding="utf-8") as fh:
            for ev in event_list:
                fh.write(events.to_json(ev))
                fh.write("\n")
                count += 1
            fh.flush()
        return count

    def load_events(self, session_id: str) -> Iterator[Event]:
        """Iterate the events of one session in write order.

        Streaming on purpose: long sessions stay friendly to memory. Callers
        that want a list should wrap with ``list(...)``.
        """
        path = self._jsonl_path(session_id)
        if not path.exists():
            raise SessionNotFound(f"session {session_id!r} not found at {path}")
        with path.open(encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                yield events.from_json(line)

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------
    def read_meta(self, session_id: str) -> SessionMeta:
        """Return meta for ``session_id``, rebuilding from JSONL if missing.

        If the sidecar exists it's the source of truth; if absent we scan the
        events to fill in what we can (``event_count``, ``created``,
        ``last_updated``). ``parent_id`` and ``title`` are unrecoverable from
        events alone and default to ``None`` after a rebuild.
        """
        meta_path = self._meta_path(session_id)
        if meta_path.exists():
            return SessionMeta.from_json(meta_path.read_text(encoding="utf-8"))
        return self._rebuild_meta(session_id)

    def write_meta(self, session_id: str, meta: SessionMeta) -> None:
        """Atomically write ``meta`` to the sidecar via tmp + ``os.replace``."""
        if meta.session_id != session_id:
            raise ValueError(f"meta.session_id ({meta.session_id!r}) must match {session_id!r}")
        self._validate_id(session_id)
        self._ensure_root()
        meta_path = self._meta_path(session_id)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{session_id}.meta.", suffix=".tmp", dir=str(self._root)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(meta.to_json())
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, meta_path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise

    def set_title(self, session_id: str, title: str | None) -> SessionMeta:
        meta = self.read_meta(session_id)
        meta.title = title
        meta.last_updated = _utcnow_iso()
        self.write_meta(session_id, meta)
        return meta

    def _rebuild_meta(self, session_id: str) -> SessionMeta:
        """Reconstruct meta by scanning the JSONL — fallback for missing sidecar."""
        path = self._jsonl_path(session_id)
        if not path.exists():
            raise SessionNotFound(f"session {session_id!r} not found at {path}")
        count = 0
        first_ts: str | None = None
        last_ts: str | None = None
        for ev in self.load_events(session_id):
            count += 1
            ts = ev.ts.isoformat()
            if first_ts is None:
                first_ts = ts
            last_ts = ts
        return SessionMeta(
            session_id=session_id,
            parent_id=None,
            title=None,
            created=first_ts or _utcnow_iso(),
            last_updated=last_ts or _utcnow_iso(),
            event_count=count,
        )

    # ------------------------------------------------------------------
    # Export / import
    # ------------------------------------------------------------------
    def export(self, session_id: str, dest_path: str | Path) -> Path:
        """Write the session's JSONL to ``dest_path`` plus a sidecar meta.

        SPEC §11.2 takes a single ``.jsonl`` path; we honor that and emit
        ``{dest}.meta.json`` next to it so ``title``/``created``/``parent_id``
        survive the round trip. Returns the destination JSONL path.
        """
        src = self._jsonl_path(session_id)
        if not src.exists():
            raise SessionNotFound(f"session {session_id!r} not found at {src}")
        dest = Path(dest_path)
        if dest.parent and not dest.parent.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        meta = self.read_meta(session_id)
        _export_meta_path(dest).write_text(meta.to_json(), encoding="utf-8")
        return dest

    def import_(self, src_path: str | Path) -> str:
        """Import a previously-exported session into this store.

        Reuses the source ``session_id`` (from the sidecar meta if present,
        otherwise from the first event in the JSONL). On collision with an
        existing local session id, raises :class:`FileExistsError` so the
        caller can rename or delete the existing one. Returns the session id.
        """
        src = Path(src_path)
        if not src.exists():
            raise FileNotFoundError(f"import source not found: {src}")
        sidecar = _export_meta_path(src)
        meta: SessionMeta | None
        if sidecar.exists():
            meta = SessionMeta.from_json(sidecar.read_text(encoding="utf-8"))
            sid = meta.session_id
        else:
            meta = None
            sid = _first_event_session_id(src)
        self._validate_id(sid)
        if self.exists(sid):
            raise FileExistsError(
                f"session {sid!r} already exists in {self._root}; remove it before importing"
            )
        self._ensure_root()
        shutil.copy2(src, self._jsonl_path(sid))
        if meta is None:
            meta = self._rebuild_meta(sid)
        self.write_meta(sid, meta)
        return sid


def _export_meta_path(jsonl_path: Path) -> Path:
    """Sidecar path next to an export file: ``foo.jsonl`` → ``foo.meta.json``."""
    return jsonl_path.with_suffix(".meta.json")


def _first_event_session_id(jsonl: Path) -> str:
    with jsonl.open(encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            ev = events.from_json(line)
            return ev.session_id
    raise ValueError(f"cannot infer session_id: {jsonl} has no events")


__all__ = [
    "InvalidSessionId",
    "SessionMeta",
    "SessionNotFound",
    "SessionStore",
]
