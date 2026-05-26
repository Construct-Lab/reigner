"""Persisted fork-tree navigation tests for T-25."""

from __future__ import annotations

from pathlib import Path

import pytest

from reigner.sessions.store import SessionMeta, SessionNotFound, SessionStore
from reigner.sessions.tree import build_forest, tree


def _session(
    store: SessionStore,
    session_id: str,
    *,
    parent_id: str | None = None,
    created: str = "2026-05-25T00:00:00+00:00",
) -> None:
    store.write_session_events(session_id, [])
    store.write_meta(
        session_id,
        SessionMeta(session_id=session_id, parent_id=parent_id, created=created),
    )


def test_build_forest_links_branches_and_sorts_children(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    _session(store, "root", created="2026-05-25T00:00:00+00:00")
    _session(store, "later", parent_id="root", created="2026-05-25T02:00:00+00:00")
    _session(store, "earlier", parent_id="root", created="2026-05-25T01:00:00+00:00")
    _session(store, "grandchild", parent_id="earlier", created="2026-05-25T03:00:00+00:00")

    [root] = build_forest(store)

    assert root.session_id == "root"
    assert [child.session_id for child in root.children] == ["earlier", "later"]
    assert [node.session_id for node in root.walk()] == [
        "root",
        "earlier",
        "grandchild",
        "later",
    ]


def test_tree_returns_whole_family_and_marks_target(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    _session(store, "root")
    _session(store, "child", parent_id="root")

    root = tree(store, "child")

    assert root.session_id == "root"
    marked = [node.session_id for node in root.walk() if node.marked]
    assert marked == ["child"]


def test_orphan_parent_promotes_child_to_root(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    _session(store, "orphan", parent_id="missing")

    [root] = build_forest(store)

    assert root.session_id == "orphan"


def test_cycle_is_broken_without_recursive_walk(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    _session(store, "a", parent_id="b", created="2026-05-25T00:00:00+00:00")
    _session(store, "b", parent_id="a", created="2026-05-25T01:00:00+00:00")

    forest = build_forest(store)
    ids = [node.session_id for root in forest for node in root.walk()]

    assert sorted(ids) == ["a", "b"]
    assert len(ids) == 2


def test_tree_missing_session_raises(tmp_path: Path) -> None:
    with pytest.raises(SessionNotFound):
        tree(SessionStore(tmp_path), "missing")
