"""Behavior tests for `reigner session` (T-21).

Read commands (list/show/tree/export/import) build sessions on disk via
``SessionStore`` directly — no harness, no model. The mutating commands
(fork/replay) monkeypatch ``session._build_harness`` to hand back a
``FakeAdapter`` harness pointed at the test store, so they stay deterministic
and never reach a provider. The ``--with-role`` seam is tested both at the
CLI boundary (the path reaches ``_build_harness``) and at ``_load_role``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reigner.cli.__main__ import app
from reigner.config import SessionsConfig
from reigner.harness.adapters.base import ModelAction, TokenUsage
from reigner.harness.agent import Harness
from reigner.harness.events import CitationEvent, Event, FinalAnswerEvent, UserQueryEvent
from reigner.sessions.store import SessionMeta, SessionStore
from reigner.types import ConfigError
from tests.harness.test_loop import FakeAdapter

runner = CliRunner()

_YAML = """\
name: test
version: 0.1.0
model:
  provider: openai
  name: gpt-4o
role:
  file: REIGNER.md
  skills: []
sessions:
  store_path: ./.reigner/sessions
  auto_save: true
"""


def _final(text: str = "done") -> ModelAction:
    return ModelAction(
        is_final_answer=True,
        text=text,
        tool_calls=[],
        usage=TokenUsage.empty(),
        stop_reason="end_turn",
    )


def _run(args: list[str], cwd: Path):
    old = os.getcwd()
    os.chdir(cwd)
    try:
        return runner.invoke(app, args, catch_exceptions=False)
    finally:
        os.chdir(old)


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "reigner.yaml").write_text(_YAML)
    (tmp_path / "REIGNER.md").write_text("# Base role\n")
    yield tmp_path


def _store(project: Path) -> SessionStore:
    return SessionStore(project / ".reigner" / "sessions")


Round = tuple[str, str | None, list[str]]  # (query, final_answer, citation_sources)


def _events_for(sid: str, rounds: list[Round]) -> list[Event]:
    evs: list[Event] = []
    seq = 0
    for i, (query, answer, cites) in enumerate(rounds):
        evs.append(UserQueryEvent(seq=seq, session_id=sid, turn=0, query=query))
        seq += 1
        for src in cites:
            evs.append(
                CitationEvent(
                    seq=seq, session_id=sid, turn=i + 1, source=src, locator={}, value=None
                )
            )
            seq += 1
        if answer is not None:
            evs.append(
                FinalAnswerEvent(seq=seq, session_id=sid, turn=i + 1, text=answer, metadata={})
            )
            seq += 1
    return evs


def _make(
    store: SessionStore,
    sid: str,
    rounds: list[Round],
    *,
    parent_id: str | None = None,
    title: str | None = None,
) -> None:
    evs = _events_for(sid, rounds)
    store.write_session_events(sid, evs)
    store.write_meta(
        store_id := sid,
        SessionMeta(session_id=store_id, parent_id=parent_id, title=title, event_count=len(evs)),
    )


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_empty(project: Path) -> None:
    result = _run(["session", "list"], project)
    assert result.exit_code == 0
    assert "no sessions" in result.output


def test_list_tabulates_sessions(project: Path) -> None:
    store = _store(project)
    _make(store, "aaaa1111", [("q1", "a1", [])], title="First")
    _make(store, "bbbb2222", [("q1", "a1", []), ("q2", "a2", [])])

    result = _run(["session", "list"], project)
    assert result.exit_code == 0
    assert "aaaa1111" in result.output
    assert "First" in result.output
    assert "2 session(s)" in result.output


def test_list_json(project: Path) -> None:
    store = _store(project)
    _make(store, "aaaa1111", [("q1", "a1", [])], title="First")

    result = _run(["session", "list", "--json"], project)
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert [m["session_id"] for m in data] == ["aaaa1111"]
    assert data[0]["title"] == "First"


# ---------------------------------------------------------------------------
# show + id resolution
# ---------------------------------------------------------------------------


def test_show_renders_rounds_and_citations(project: Path) -> None:
    store = _store(project)
    _make(
        store,
        "aaaa1111",
        [("What is X?", "X is 42.", ["DOC/2024/metrics.json"])],
        title="Q",
    )

    result = _run(["session", "show", "aaaa1111"], project)
    assert result.exit_code == 0
    assert "What is X?" in result.output
    assert "X is 42." in result.output
    assert "DOC/2024/metrics.json" in result.output


def test_show_resolves_unambiguous_prefix(project: Path) -> None:
    store = _store(project)
    _make(store, "aaaa1111", [("q", "a", [])])

    result = _run(["session", "show", "aaaa"], project)
    assert result.exit_code == 0
    assert "aaaa1111" in result.output


def test_show_ambiguous_prefix_errors(project: Path) -> None:
    store = _store(project)
    _make(store, "aaaa1111", [("q", "a", [])])
    _make(store, "aaaa2222", [("q", "a", [])])

    result = _run(["session", "show", "aaaa"], project)
    assert result.exit_code == 2
    assert "ambiguous" in result.output


def test_show_missing_prefix_errors(project: Path) -> None:
    store = _store(project)
    _make(store, "aaaa1111", [("q", "a", [])])

    result = _run(["session", "show", "zzzz"], project)
    assert result.exit_code == 2
    assert "no session matching" in result.output


def test_show_json(project: Path) -> None:
    store = _store(project)
    _make(store, "aaaa1111", [("q1", "a1", ["S"]), ("q2", None, [])])

    result = _run(["session", "show", "aaaa1111", "--json"], project)
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data["rounds"]) == 2
    assert data["rounds"][0]["citations"] == ["S"]
    assert data["rounds"][1]["final_answer"] is None


# ---------------------------------------------------------------------------
# tree
# ---------------------------------------------------------------------------


def test_tree_marks_queried_node(project: Path) -> None:
    store = _store(project)
    _make(store, "root0000", [("q", "a", [])])
    _make(store, "child001", [("q", "a", [])], parent_id="root0000")

    result = _run(["session", "tree", "child001"], project)
    assert result.exit_code == 0
    assert "root0000" in result.output
    assert "child001" in result.output
    assert "queried" in result.output


def test_tree_json_nests_children(project: Path) -> None:
    store = _store(project)
    _make(store, "root0000", [("q", "a", [])])
    _make(store, "child001", [("q", "a", [])], parent_id="root0000")

    result = _run(["session", "tree", "child001", "--json"], project)
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["session_id"] == "root0000"
    assert data["children"][0]["session_id"] == "child001"
    assert data["children"][0]["marked"] is True


# ---------------------------------------------------------------------------
# export / import
# ---------------------------------------------------------------------------


def test_export_then_import_roundtrips(project: Path, tmp_path: Path) -> None:
    store = _store(project)
    _make(store, "aaaa1111", [("q", "a", [])], title="Exported")
    dest = tmp_path / "out.jsonl"

    export = _run(["session", "export", "aaaa1111", "--to", str(dest)], project)
    assert export.exit_code == 0
    assert dest.exists()

    # Import into a fresh project so the id doesn't collide.
    (other := tmp_path / "other").mkdir()
    (other / "reigner.yaml").write_text(_YAML)
    imported = _run(["session", "import", str(dest)], other)
    assert imported.exit_code == 0
    assert "aaaa1111" in imported.output
    assert _store(other).exists("aaaa1111")


def test_import_missing_file_errors(project: Path) -> None:
    result = _run(["session", "import", "nope.jsonl"], project)
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# fork / replay  (fake-adapter harness)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_harness(project: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Patch ``session._build_harness`` to a FakeAdapter harness on the test store.

    Returns a dict that captures the ``role_file`` argument each build saw, so a
    test can assert ``--with-role`` reached the seam.
    """
    from reigner.cli import session as session_mod

    store_root = str(project / ".reigner" / "sessions")
    captured: dict[str, object] = {}

    def _fake(config: str, *, role_file: str | None = None) -> Harness:
        captured["role_file"] = role_file
        return Harness(
            adapter=FakeAdapter(actions=[_final("replayed")]),
            role="BASE",
            sessions=SessionsConfig(store_path=store_root),
        )

    monkeypatch.setattr(session_mod, "_build_harness", _fake)
    return captured


def test_fork_creates_child(project: Path, fake_harness: dict[str, object]) -> None:
    store = _store(project)
    _make(store, "aaaa1111", [("q1", "a1", []), ("q2", "a2", [])])

    result = _run(["session", "fork", "aaaa1111", "--at-turn", "2"], project)
    assert result.exit_code == 0
    assert "forked" in result.output
    assert len(store.list()) == 2  # parent + new child


def test_fork_bad_turn_errors(project: Path, fake_harness: dict[str, object]) -> None:
    store = _store(project)
    _make(store, "aaaa1111", [("q1", "a1", [])])

    result = _run(["session", "fork", "aaaa1111", "--at-turn", "9"], project)
    assert result.exit_code == 2


def test_replay_reruns_round(project: Path, fake_harness: dict[str, object]) -> None:
    store = _store(project)
    _make(store, "aaaa1111", [("q1", "a1", []), ("q2", "a2", [])])

    result = _run(["session", "replay", "aaaa1111", "--at-turn", "1"], project)
    assert result.exit_code == 0
    assert "replayed round 1" in result.output
    assert len(store.list()) == 2  # original + replay child


def test_replay_default_targets_last_round(project: Path, fake_harness: dict[str, object]) -> None:
    store = _store(project)
    _make(store, "aaaa1111", [("q1", "a1", []), ("q2", "a2", [])])

    result = _run(["session", "replay", "aaaa1111"], project)
    assert result.exit_code == 0
    assert "replayed round 2" in result.output


def test_replay_out_of_range_errors(project: Path, fake_harness: dict[str, object]) -> None:
    store = _store(project)
    _make(store, "aaaa1111", [("q1", "a1", [])])

    result = _run(["session", "replay", "aaaa1111", "--at-turn", "9"], project)
    assert result.exit_code == 2
    assert "out of range" in result.output


def test_replay_with_role_reaches_seam(project: Path, fake_harness: dict[str, object]) -> None:
    store = _store(project)
    _make(store, "aaaa1111", [("q1", "a1", [])])
    (project / "ALT.md").write_text("# Alt role\n")

    result = _run(["session", "replay", "aaaa1111", "--with-role", "ALT.md"], project)
    assert result.exit_code == 0
    assert fake_harness["role_file"] == "ALT.md"


# ---------------------------------------------------------------------------
# inspect session  (alias for session show)
# ---------------------------------------------------------------------------


def test_inspect_session_aliases_show(project: Path) -> None:
    store = _store(project)
    _make(store, "aaaa1111", [("What is X?", "X is 42.", [])])

    result = _run(["inspect", "session", "aaaa1111"], project)
    assert result.exit_code == 0
    assert "What is X?" in result.output
    assert "X is 42." in result.output


# ---------------------------------------------------------------------------
# Harness.from_config role_file seam
# ---------------------------------------------------------------------------


@pytest.fixture
def _no_adapter(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """Stub the provider adapter so from_config needs no SDK / API key."""

    def _install() -> None:
        from reigner.harness import agent as agent_mod

        monkeypatch.setattr(agent_mod, "_build_adapter", lambda provider, model: object())

    return _install


def test_from_config_role_file_overrides_role(
    project: Path, _no_adapter: Callable[[], None]
) -> None:
    _no_adapter()
    (project / "ALT.md").write_text("# Alt role\nDifferent instructions.\n")

    harness = Harness.from_config(project / "reigner.yaml", role_file=project / "ALT.md")
    assert "Different instructions." in harness.role


def test_from_config_role_file_missing_raises(
    project: Path, _no_adapter: Callable[[], None]
) -> None:
    _no_adapter()
    with pytest.raises(ConfigError):
        Harness.from_config(project / "reigner.yaml", role_file=project / "nope.md")
