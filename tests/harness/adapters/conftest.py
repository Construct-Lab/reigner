"""Shared fixtures: a fake ToolSpec and a sample Prompt for adapter tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from reigner.harness.state import Prompt, Turn


@dataclass
class FakeTool:
    name: str = "get_weather"
    description: str = "Get current weather."
    readonly: bool = True

    def json_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
            "additionalProperties": False,
        }


@pytest.fixture
def tool() -> FakeTool:
    return FakeTool()


@pytest.fixture
def prompt() -> Prompt:
    return Prompt(
        stable="ROLE: you are a test agent.\nTOOLS: get_weather",
        dynamic_context={"iters_remaining": 5},
        messages=[Turn(role="user", content="What is the weather in Paris?")],
    )
