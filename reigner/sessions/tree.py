"""Fork-tree construction and navigation for durable sessions (SPEC §11, T-25)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from reigner.sessions.store import SessionMeta, SessionNotFound, SessionStore


@dataclass
class SessionNode:
    """One session in a fork tree."""

    session_id: str
    meta: SessionMeta
    children: list[SessionNode] = field(default_factory=list)
    marked: bool = False

    def walk(self) -> Iterator[SessionNode]:
        """Yield this node and all descendants in display order."""
        yield self
        for child in self.children:
            yield from child.walk()


def _sort_key(node: SessionNode) -> tuple[str, str]:
    return (node.meta.created, node.session_id)


def _contains(root: SessionNode, target: SessionNode) -> bool:
    return any(node is target for node in root.walk())


def _sort_descendants(node: SessionNode) -> None:
    node.children.sort(key=_sort_key)
    for child in node.children:
        _sort_descendants(child)


def build_forest(store: SessionStore) -> list[SessionNode]:
    """Build all session families from persisted ``parent_id`` relationships.

    Sessions with a missing parent are roots. Corrupt cyclic lineage never
    creates a recursive graph: the edge that would close a cycle is skipped,
    promoting that node to a root instead.
    """
    nodes = {
        meta.session_id: SessionNode(session_id=meta.session_id, meta=meta) for meta in store.list()
    }
    roots: list[SessionNode] = []

    for node in sorted(nodes.values(), key=_sort_key):
        parent_id = node.meta.parent_id
        parent = nodes.get(parent_id) if parent_id is not None else None
        if parent is None or parent is node or _contains(node, parent):
            roots.append(node)
            continue
        parent.children.append(node)

    roots.sort(key=_sort_key)
    for root in roots:
        _sort_descendants(root)
    return roots


def tree(store: SessionStore, session_id: str) -> SessionNode:
    """Return the complete tree containing ``session_id``, marking that node."""
    if not store.exists(session_id):
        raise SessionNotFound(f"session {session_id!r} not found at {store.root}")

    for root in build_forest(store):
        for node in root.walk():
            if node.session_id == session_id:
                node.marked = True
                return root
    raise SessionNotFound(f"session {session_id!r} has no readable session metadata")


__all__ = ["SessionNode", "build_forest", "tree"]
