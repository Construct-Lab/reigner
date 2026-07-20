"""Model adapters: translate the harness Prompt into provider-specific calls.

Each adapter owns one provider; the loop talks only to the `ModelAdapter`
Protocol in `base`.
"""

from typing import get_args

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
from reigner.types import ConfigError, EffortLevel, ProviderName


def build_adapter(
    provider: ProviderName,
    model: str,
    effort: EffortLevel = "medium",
    temperature: float | None = None,
) -> ModelAdapter:
    """Resolve a provider literal to a concrete adapter instance.

    The single canonical builder: one place to add a provider, one place to
    enforce the :data:`~reigner.types.ProviderName` literal, one error contract.
    Lazy-imports the per-provider module so users only pay for the SDK they use;
    a missing optional dependency surfaces as a clear :class:`ConfigError` rather
    than an opaque ``ImportError`` deep in adapter code.

    ``effort`` and ``temperature`` are threaded from :class:`ModelConfig`. Each
    adapter maps ``effort`` to its provider's reasoning knob (behind a
    model-capability guard) and emits ``temperature`` only when explicitly set
    and accepted by the model — never on the frontier reasoning path.
    """
    try:
        if provider == "openai":
            from reigner.harness.adapters.openai import OpenAIAdapter

            return OpenAIAdapter(model=model, effort=effort, temperature=temperature)
        if provider == "anthropic":
            from reigner.harness.adapters.anthropic import AnthropicAdapter

            return AnthropicAdapter(model=model, effort=effort, temperature=temperature)
        if provider == "gemini":
            from reigner.harness.adapters.gemini import GeminiAdapter

            return GeminiAdapter(model=model, effort=effort, temperature=temperature)
    except ImportError as e:
        raise ConfigError(
            f"provider {provider!r} requires its optional dependency to be "
            f"installed (e.g. `uv add reigner[{provider}]`): {e}"
        ) from e

    # Fall-through is the runtime enforcement of the ProviderName literal — it
    # also catches raw ``str`` inputs (e.g. from resolve_adapter) that dodged
    # static checking. Derive the supported list from the literal so the message
    # can never drift from what is actually wired.
    supported = ", ".join(get_args(ProviderName))
    raise ConfigError(f"unknown model provider {provider!r}. Supported providers: {supported}.")


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
    "build_adapter",
]
