"""PluginHost dispatch: the transform fold and the split failure policy (SPEC §12).

Exercised in isolation with sentinel values — the host doesn't inspect the
objects it threads through, only chains them across plugins.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from reigner.plugins.base import Plugin
from reigner.plugins.hooks import OBSERVE_HOOKS, TRANSFORM_HOOKS, PluginHookError
from reigner.plugins.host import PluginHost


class Append(Plugin):
    """A transform plugin that appends its tag to the threaded string value."""

    def __init__(self, tag: str) -> None:
        self.name = tag

    async def before_tool_call(self, call: Any, state: Any) -> Any:
        return f"{call}+{self.name}"

    async def after_tool_call(self, call: Any, result: Any, state: Any) -> Any:
        return f"{result}+{self.name}"

    async def on_final_answer(self, answer: Any, state: Any) -> Any:
        return f"{answer}+{self.name}"


class RaisingTransform(Plugin):
    name = "boom"

    async def after_tool_call(self, call: Any, result: Any, state: Any) -> Any:
        raise ValueError("nope")


class UnnamedTransform(Plugin):
    async def before_tool_call(self, call: Any, state: Any) -> Any:
        raise ValueError("nope")


class RaisingObserver(Plugin):
    name = "obs-boom"

    async def on_compaction(self, state: Any, level: int) -> None:
        raise RuntimeError("sink down")


class RecordingObserver(Plugin):
    name = "obs-rec"

    def __init__(self) -> None:
        self.levels: list[int] = []

    async def on_compaction(self, state: Any, level: int) -> None:
        self.levels.append(level)


# --------------------------------------------------------------------------
# Transform hooks — fold + fail-loud
# --------------------------------------------------------------------------


async def test_before_tool_call_folds_in_order() -> None:
    host = PluginHost([Append("a"), Append("b")])
    assert await host.before_tool_call("call", state=None) == "call+a+b"


async def test_after_and_final_answer_fold_too() -> None:
    host = PluginHost([Append("a"), Append("b")])
    assert await host.after_tool_call("c", "r", state=None) == "r+a+b"
    assert await host.on_final_answer("ans", state=None) == "ans+a+b"


async def test_transform_failure_raises_plugin_hook_error() -> None:
    host = PluginHost([RaisingTransform()])
    with pytest.raises(PluginHookError) as ei:
        await host.after_tool_call("c", "r", state=None)
    assert ei.value.plugin_name == "boom"
    assert ei.value.hook == "after_tool_call"
    assert isinstance(ei.value.__cause__, ValueError)


async def test_transform_failure_stops_the_fold() -> None:
    later = Append("later")
    host = PluginHost([RaisingTransform(), later])
    with pytest.raises(PluginHookError):
        await host.after_tool_call("c", "r", state=None)


async def test_label_falls_back_to_class_name() -> None:
    host = PluginHost([UnnamedTransform()])
    with pytest.raises(PluginHookError) as ei:
        await host.before_tool_call("c", state=None)
    assert ei.value.plugin_name == "UnnamedTransform"


# --------------------------------------------------------------------------
# Observe hooks — run all, isolate failures
# --------------------------------------------------------------------------


async def test_observe_failure_is_isolated(caplog: pytest.LogCaptureFixture) -> None:
    rec = RecordingObserver()
    host = PluginHost([RaisingObserver(), rec])
    with caplog.at_level(logging.WARNING, logger="reigner.plugins"):
        await host.on_compaction(state=None, level=2)  # must not raise
    assert rec.levels == [2]  # a later plugin still ran
    assert "on_compaction failed" in caplog.text
    assert "obs-boom" in caplog.text


# --------------------------------------------------------------------------
# Empty host + classification invariants
# --------------------------------------------------------------------------


async def test_empty_host_is_passthrough() -> None:
    host = PluginHost.empty()
    assert not host
    assert len(host) == 0
    assert await host.before_tool_call("c", state=None) == "c"
    assert await host.after_tool_call("c", "r", state=None) == "r"
    assert await host.on_final_answer("a", state=None) == "a"
    await host.on_error("e", state=None)  # no-op, no raise


def test_hook_classification_is_disjoint_and_complete() -> None:
    assert TRANSFORM_HOOKS.isdisjoint(OBSERVE_HOOKS)
    assert len(TRANSFORM_HOOKS | OBSERVE_HOOKS) == 7
