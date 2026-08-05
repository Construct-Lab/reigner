"""Startup-surface tests for `reigner serve --http`.

``uvicorn.run`` is monkeypatched away — these assert on what the operator sees
printed before the server blocks, not on a live socket.
"""

from __future__ import annotations

import pytest

from reigner.cli import serve as serve_mod
from reigner.config import ModelConfig, ReignerConfig, SettingsConfig
from reigner.harness.adapters.base import ModelAction
from reigner.harness.agent import Harness
from tests.harness.test_loop import FakeAdapter, _final


@pytest.fixture
def run_http(monkeypatch: pytest.MonkeyPatch):
    """Call ``_run_http`` with uvicorn stubbed; return the host/port it got."""
    import uvicorn

    called: dict[str, object] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: called.update(kw))

    def _call(*, host: str = "127.0.0.1", port: int = 8000) -> dict[str, object]:
        cfg = ReignerConfig(name="test_agent", model=ModelConfig(provider="openai", name="gpt-5.5"))
        actions: list[ModelAction | Exception] = [_final("hi")]
        harness = Harness(
            adapter=FakeAdapter(actions=actions), role="TEST", settings=SettingsConfig()
        )
        serve_mod._run_http(cfg, harness, host=host, port=port)
        return called

    return _call


def test_startup_lists_every_route(run_http, capsys: pytest.CaptureFixture[str]) -> None:
    run_http()
    out = capsys.readouterr().out
    assert "listening on http://127.0.0.1:8000" in out
    for route in ("POST /run", "GET /sessions", "GET /sessions/{id}/events", "GET /health"):
        assert route in out


def test_loopback_bind_prints_no_warning(run_http, capsys: pytest.CaptureFixture[str]) -> None:
    run_http()
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "::"])
def test_exposed_bind_warns_on_stderr(
    run_http, capsys: pytest.CaptureFixture[str], host: str
) -> None:
    run_http(host=host)
    err = capsys.readouterr().err
    assert "no auth, CORS, or rate limiting" in err
    assert "gateway" in err


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_spellings_are_all_quiet(
    run_http, capsys: pytest.CaptureFixture[str], host: str
) -> None:
    run_http(host=host)
    assert capsys.readouterr().err == ""


def test_hostname_binds_are_treated_as_exposed(
    run_http, capsys: pytest.CaptureFixture[str]
) -> None:
    # A name we can't resolve to an address gets the warning — a spurious
    # caution costs nothing, silence on a public bind costs a lot.
    run_http(host="agent.internal")
    assert "no auth" in capsys.readouterr().err
