"""Session.steer enqueues onto AgentState.pending_steering (T-19 pull-forward).

The loop's consumption of pending_steering lands with T-06; this test pins the
wrapper contract so the CLI can rely on it today.
"""

from __future__ import annotations

import pytest

from tests.harness.test_loop import FakeAdapter, _final, _harness


@pytest.mark.asyncio
async def test_steer_enqueues_with_default_mode() -> None:
    session = _harness(adapter=FakeAdapter(actions=[_final()]), tools=[]).session()
    await session.steer("focus on §3")
    assert session._state.pending_steering == [("focus on §3", "interrupt")]


@pytest.mark.asyncio
async def test_steer_preserves_order_and_mode() -> None:
    session = _harness(adapter=FakeAdapter(actions=[_final()]), tools=[]).session()
    await session.steer("first", "queue")
    await session.steer("second", "interrupt")
    assert session._state.pending_steering == [
        ("first", "queue"),
        ("second", "interrupt"),
    ]
    assert session._state.has_pending_steering()
