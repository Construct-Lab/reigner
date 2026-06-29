"""Model adapters: translate the harness Prompt into provider-specific calls.

Each adapter owns one provider; the loop talks only to the `ModelAdapter`
Protocol in `base`.
"""

from reigner.harness.adapters.base import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimitError,
    ModelAction,
    ModelAdapter,
    StopReason,
    TokenUsage,
    ToolCall,
    TransientAdapterError,
)

__all__ = [
    "AdapterAuthError",
    "AdapterError",
    "AdapterRateLimitError",
    "ModelAction",
    "ModelAdapter",
    "StopReason",
    "TokenUsage",
    "ToolCall",
    "TransientAdapterError",
]
