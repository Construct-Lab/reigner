"""Unit tests for harness.oracle (T-06, SPEC §5.5)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from reigner.harness.oracle import OracleNotConfigured, arm, pick_adapter
from reigner.harness.state import AgentState


@dataclass
class _StubAdapter:
    name: str = "stub"
    model: str = "stub-model"


def _state(**kw: object) -> AgentState:
    base: dict[str, object] = {
        "session_id": "s",
        "role": "r",
        "token_counter": lambda s: len(s),
    }
    base.update(kw)
    return AgentState(**base)  # type: ignore[arg-type]


def test_pick_adapter_defaults_to_base() -> None:
    base = _StubAdapter(name="base")
    oracle = _StubAdapter(name="oracle")
    s = _state(adapter=base, oracle_adapter=oracle)
    assert pick_adapter(s) is base


def test_arm_then_pick_returns_oracle_once() -> None:
    base = _StubAdapter(name="base")
    oracle = _StubAdapter(name="oracle")
    s = _state(adapter=base, oracle_adapter=oracle)

    arm(s)
    assert s.oracle_armed is True

    assert pick_adapter(s) is oracle
    assert s.oracle_armed is False  # cleared after one consumption
    assert pick_adapter(s) is base  # reverts


def test_arm_without_oracle_raises() -> None:
    s = _state(adapter=_StubAdapter(), oracle_adapter=None)
    with pytest.raises(OracleNotConfigured):
        arm(s)


def test_pick_adapter_no_adapter_raises() -> None:
    s = _state()
    with pytest.raises(RuntimeError):
        pick_adapter(s)
