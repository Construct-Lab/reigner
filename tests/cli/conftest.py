"""Shared fixtures for CLI tests — fake adapter + pre-built Session.

The chat command's tests want to avoid hitting a real provider. We build a
``Harness`` with a scripted ``FakeAdapter`` (reused from ``test_loop``) and
monkey-patch ``reigner.cli.chat._build_session`` to return it. This sidesteps
config loading entirely and keeps the test deterministic.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from reigner.config import SettingsConfig
from reigner.harness.adapters.base import ModelAction, TokenUsage
from reigner.harness.agent import Harness, Session
from tests.harness.test_loop import FakeAdapter


def _final(text: str = "done") -> ModelAction:
    return ModelAction(
        is_final_answer=True,
        text=text,
        tool_calls=[],
        usage=TokenUsage.empty(),
        stop_reason="end_turn",
    )


@pytest.fixture
def make_session() -> Callable[..., Session]:
    """Return a builder for a Session backed by a scripted FakeAdapter."""

    def _build(actions: list[ModelAction] | None = None) -> Session:
        adapter = FakeAdapter(actions=list(actions or [_final("hello world")]))
        harness = Harness(
            adapter=adapter,
            role="TEST",
            settings=SettingsConfig(),
        )
        return harness.session()

    return _build


@pytest.fixture
def patch_build_session(
    monkeypatch: pytest.MonkeyPatch,
    make_session: Callable[..., Session],
) -> Callable[..., Session]:
    """Patch ``chat._build_session`` to hand the CLI a fake-adapter Session.

    Returns the session so the test can inspect ``session._state`` afterwards.
    """
    from reigner.cli import chat as chat_module

    def _install(actions: list[ModelAction] | None = None) -> Session:
        session = make_session(actions)
        monkeypatch.setattr(chat_module, "_build_session", lambda _p: session)
        return session

    return _install


__all__ = ["_final", "make_session", "patch_build_session"]
