"""Shared fixtures for ingestion tests.

The :class:`StubAdapter` lets us drive ``LLMExtractor`` without any real
provider SDK. Each call pops the next item off ``responses``: a string is
returned as :attr:`ModelAction.text`, an exception is raised. ``calls``
records every invocation for assertions.
"""

from __future__ import annotations

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


def make_response(sections: dict[str, str], json_artifacts: dict[str, Any]) -> str:
    """Convenience: build the JSON-string response a happy-path stub returns."""
    import json as _json

    return _json.dumps({"sections": sections, "json_artifacts": json_artifacts})
