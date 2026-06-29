"""Anthropic adapter.

Marks `Prompt.stable` with `cache_control={"type": "ephemeral"}` so the
provider caches the role + tool schemas prefix across iterations (G1 pays off
here). Tools use `input_schema`, not `parameters`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from reigner.harness.adapters.base import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimitError,
    ModelAction,
    StopReason,
    TokenUsage,
    ToolCall,
    TransientAdapterError,
    render_tool_for_anthropic,
)
from reigner.harness.state import Prompt, ToolSpec, Turn

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic


@dataclass
class AnthropicAdapter:
    """Model adapter for Anthropic Claude via the ``anthropic`` SDK."""

    model: str = "claude-opus-4-7"
    api_key: str | None = None
    max_tokens: int = 4096
    name: str = "anthropic"
    supports_prompt_caching: bool = True

    _client: AsyncAnthropic | None = None

    def _get_client(self) -> AsyncAnthropic:
        if self._client is not None:
            return self._client
        try:
            from anthropic import AsyncAnthropic
        except ImportError as e:
            raise AdapterError(
                "anthropic package not installed. Install with `pip install reigner[anthropic]`."
            ) from e
        kwargs: dict[str, Any] = {}
        if self.api_key is not None:
            kwargs["api_key"] = self.api_key
        self._client = AsyncAnthropic(**kwargs)
        return self._client

    async def call(self, prompt: Prompt, tools: list[ToolSpec]) -> ModelAction:
        """Call Claude with the prompt and tools, returning a ModelAction.

        Args:
            prompt: The harness prompt (stable prefix + turns).
            tools: Tool specs to expose to the model this turn.

        Returns:
            The provider response normalized into a :class:`ModelAction`.
        """
        client = self._get_client()
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": prompt.stable,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": _turns_to_messages(prompt.messages),
        }
        if tools:
            payload["tools"] = [render_tool_for_anthropic(t) for t in tools]

        try:
            response = await client.messages.create(**payload)
        except Exception as e:  # noqa: BLE001
            raise _wrap_anthropic_error(e) from e

        return _parse_response(response)


def _turns_to_messages(turns: list[Turn]) -> list[dict[str, Any]]:
    """Translate Turns into Anthropic's nested content-block format.

    Assistant turns with tool_calls become an assistant message containing
    `tool_use` blocks (plus an optional preceding text block). Tool result
    turns become a user message with a `tool_result` content block keyed by
    the matching `tool_use_id`.
    """
    messages: list[dict[str, Any]] = []
    for t in turns:
        if t.role == "tool":
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": t.tool_call_id or "",
                            "content": t.content,
                        }
                    ],
                }
            )
            continue
        if t.role == "assistant" and t.tool_calls:
            blocks: list[dict[str, Any]] = []
            if t.content:
                blocks.append({"type": "text", "text": t.content})
            for call in t.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.get("id", ""),
                        "name": call.get("name", ""),
                        "input": call.get("args", {}),
                    }
                )
            messages.append({"role": "assistant", "content": blocks})
            continue
        messages.append({"role": t.role, "content": t.content})
    return messages


def _parse_response(response: Any) -> ModelAction:
    tool_calls: list[ToolCall] = []
    text_chunks: list[str] = []

    for block in getattr(response, "content", None) or []:
        btype = _attr(block, "type")
        if btype == "tool_use":
            args = _attr(block, "input") or {}
            tool_calls.append(
                ToolCall(
                    id=_attr(block, "id") or "",
                    name=_attr(block, "name") or "",
                    args=args if isinstance(args, dict) else {"_value": args},
                )
            )
        elif btype == "text":
            text_chunks.append(_attr(block, "text") or "")

    text = "".join(text_chunks) or None
    raw_stop = getattr(response, "stop_reason", None) or ""
    stop_reason: StopReason
    if raw_stop == "tool_use":
        stop_reason = "tool_calls"
    elif raw_stop == "end_turn":
        stop_reason = "end_turn"
    elif raw_stop == "max_tokens":
        stop_reason = "max_tokens"
    elif raw_stop == "stop_sequence":
        stop_reason = "stop_sequence"
    else:
        stop_reason = "other"

    is_final = stop_reason == "end_turn" and bool(text) and not tool_calls

    return ModelAction(
        is_final_answer=is_final,
        text=text,
        tool_calls=tool_calls,
        usage=_extract_usage(response),
        stop_reason=stop_reason,
        raw={"id": getattr(response, "id", None), "stop_reason": raw_stop},
    )


def _attr(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _extract_usage(response: Any) -> TokenUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage.empty()
    prompt = _attr(usage, "input_tokens") or 0
    completion = _attr(usage, "output_tokens") or 0
    cache_read = _attr(usage, "cache_read_input_tokens") or 0
    cache_create = _attr(usage, "cache_creation_input_tokens") or 0
    cached = cache_read + cache_create
    return TokenUsage(
        prompt=prompt,
        completion=completion,
        cached=cached,
        total=prompt + completion,
    )


def _wrap_anthropic_error(e: Exception) -> AdapterError:
    try:
        import anthropic
    except ImportError:
        return AdapterError(str(e))

    if isinstance(e, anthropic.RateLimitError):
        return AdapterRateLimitError(str(e))
    if isinstance(e, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return AdapterAuthError(str(e))
    if isinstance(e, anthropic.APITimeoutError | anthropic.APIConnectionError):
        return TransientAdapterError(str(e))
    if isinstance(e, anthropic.APIStatusError):
        status = getattr(e, "status_code", 0) or 0
        if status >= 500:
            return TransientAdapterError(str(e))
        return AdapterError(str(e))
    return AdapterError(str(e))


__all__ = ["AnthropicAdapter"]
