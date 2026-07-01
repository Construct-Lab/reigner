"""Shared fixtures for ingestion tests.

The :class:`StubAdapter` lets us drive ``LLMExtractor`` without any real
provider SDK. Each call pops the next item off ``responses``: a string is
returned as :attr:`ModelAction.text`, an exception is raised. ``calls``
records every invocation for assertions.
"""

from __future__ import annotations

import asyncio
from typing import Any

from reigner.harness.adapters.base import (
    ModelAction,
    TokenUsage,
)
from reigner.harness.state import Prompt, ToolSpec


class StubAdapter:
    """Minimal ModelAdapter used by ingestion tests."""

    name: str = "stub"
    model: str = "stub-model"
    supports_prompt_caching: bool = False

    def __init__(
        self,
        responses: list[str | Exception],
        usage: TokenUsage | None = None,
    ) -> None:
        self._responses: list[str | Exception] = list(responses)
        self._usage = usage or TokenUsage(prompt=10, completion=20, total=30)
        self.calls: list[tuple[Prompt, list[ToolSpec]]] = []

    async def call(self, prompt: Prompt, tools: list[ToolSpec]) -> ModelAction:
        self.calls.append((prompt, list(tools)))
        if not self._responses:
            raise AssertionError("StubAdapter ran out of canned responses")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return ModelAction(
            is_final_answer=True,
            text=nxt,
            usage=self._usage,
            stop_reason="end_turn",
        )

    @property
    def remaining(self) -> int:
        return len(self._responses)


class ConcurrentStubAdapter:
    """ModelAdapter for map fan-out tests.

    Unlike :class:`StubAdapter` (FIFO by call order — which can't map a response
    to a chunk once calls interleave), this keys each response on the call's
    input text, so a response follows its chunk regardless of completion order.
    It also tracks the peak number of concurrent in-flight calls and can hold
    every call at a gate until the test releases it, so a test can observe the
    semaphore cap deterministically instead of racing on timing.

    Args:
        responses: Map of input text (the chunk sent to ``call_model``) to the
            response string, or an ``Exception`` to raise for that chunk.
        usage: Per-call token usage. Defaults to prompt=10/completion=20.
        gated: When ``True``, every call blocks at :meth:`release` until the test
            releases it. When ``False`` (default) calls proceed immediately.
        delays: Optional per-chunk ``asyncio.sleep`` before responding, used to
            force completion order to differ from submission order.
    """

    name: str = "concurrent-stub"
    model: str = "stub-model"
    supports_prompt_caching: bool = False

    def __init__(
        self,
        responses: dict[str, str | Exception],
        *,
        usage: TokenUsage | None = None,
        gated: bool = False,
        delays: dict[str, float] | None = None,
    ) -> None:
        self._responses = dict(responses)
        self._usage = usage or TokenUsage(prompt=10, completion=20, total=30)
        self._delays = dict(delays or {})
        self._gate = asyncio.Event()
        if not gated:
            self._gate.set()
        self.calls: list[tuple[Prompt, list[ToolSpec]]] = []
        self.in_flight: int = 0
        self.peak_in_flight: int = 0

    def release(self) -> None:
        """Let every gated call proceed."""
        self._gate.set()

    async def wait_until_in_flight(self, n: int) -> None:
        """Yield until at least ``n`` calls are simultaneously in flight."""
        while self.in_flight < n:
            await asyncio.sleep(0)

    async def call(self, prompt: Prompt, tools: list[ToolSpec]) -> ModelAction:
        self.calls.append((prompt, list(tools)))
        chunk = prompt.messages[0].content
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            await self._gate.wait()
            delay = self._delays.get(chunk, 0.0)
            if delay:
                await asyncio.sleep(delay)
            nxt = self._responses[chunk]
            if isinstance(nxt, Exception):
                raise nxt
            return ModelAction(
                is_final_answer=True,
                text=nxt,
                usage=self._usage,
                stop_reason="end_turn",
            )
        finally:
            self.in_flight -= 1


def make_response(sections: dict[str, str], json_artifacts: dict[str, Any]) -> str:
    """Convenience: build the JSON-string response a happy-path stub returns."""
    import json as _json

    return _json.dumps({"sections": sections, "json_artifacts": json_artifacts})
