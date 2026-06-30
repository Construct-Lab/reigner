"""OpenAI adapter — the v0 default provider.

Targets the **Responses API** (``client.responses.create``), not the legacy
Chat Completions endpoint. The flat tool shape (``{"type": "function",
"name": ..., "parameters": ..., "strict": True}``) matches Responses;
examples online showing the nested ``{"type": "function", "function": {...}}``
wrapper are Chat Completions and are wrong here.

Prompt caching is automatic on Responses for prompts >= 1024 tokens, so we
just send `Prompt.stable` verbatim as `instructions` on every call and let
OpenAI cache the prefix. No explicit cache markers needed (unlike Anthropic).
"""

from __future__ import annotations

import json
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
    render_tool_for_openai,
)
from reigner.harness.state import Prompt, ToolSpec, Turn

if TYPE_CHECKING:
    from openai import AsyncOpenAI


@dataclass
class OpenAIAdapter:
    """Default adapter. Uses the OpenAI Responses API.

    The `openai` SDK is imported lazily on first call so users who only
    install other providers don't pay the import cost.
    """

    model: str = "gpt-4o-mini"
    api_key: str | None = None
    base_url: str | None = None
    name: str = "openai"
    supports_prompt_caching: bool = True

    _client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is not None:
            return self._client
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise AdapterError(
                "openai package not installed. Install with `pip install reigner[openai]`."
            ) from e
        kwargs: dict[str, Any] = {}
        if self.api_key is not None:
            kwargs["api_key"] = self.api_key
        if self.base_url is not None:
            kwargs["base_url"] = self.base_url
        self._client = AsyncOpenAI(**kwargs)
        return self._client

    async def call(self, prompt: Prompt, tools: list[ToolSpec]) -> ModelAction:
        """Call the OpenAI Responses API, returning a ModelAction.

        Args:
            prompt: The harness prompt (stable prefix + turns).
            tools: Tool specs to expose to the model this turn.

        Returns:
            The provider response normalized into a :class:`ModelAction`.
        """
        client = self._get_client()
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": prompt.stable,
            "input": _turns_to_input(prompt.messages),
        }
        if tools:
            payload["tools"] = [render_tool_for_openai(t) for t in tools]
            payload["tool_choice"] = "auto"

        try:
            response = await client.responses.create(**payload)
        except Exception as e:  # noqa: BLE001 — narrow below
            raise _wrap_openai_error(e) from e

        return _parse_response(response)


def _turns_to_input(turns: list[Turn]) -> list[dict[str, Any]]:
    """Translate the harness Turn history into Responses-API input items.

    Responses uses a flat list of typed items. Assistant tool calls become
    standalone ``function_call`` items; tool results become
    ``function_call_output`` items keyed by `call_id`. Plain user/assistant
    text becomes role-tagged message items.
    """
    items: list[dict[str, Any]] = []
    for t in turns:
        if t.role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": t.tool_call_id or "",
                    "output": t.content,
                }
            )
            continue
        if t.role == "assistant" and t.tool_calls:
            if t.content:
                items.append({"role": "assistant", "content": t.content})
            for call in t.tool_calls:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call.get("id", ""),
                        "name": call.get("name", ""),
                        "arguments": _ensure_json_str(call.get("args", {})),
                    }
                )
            continue
        items.append({"role": t.role, "content": t.content})
    return items


def _ensure_json_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"))


def _parse_response(response: Any) -> ModelAction:
    """Pull tool calls, text, and usage out of a Responses-API response.

    The Responses API exposes outputs as `response.output` (a list of items)
    plus the convenience `response.output_text`. We walk `output` so we never
    mistake a tool-call response for a final answer.
    """
    tool_calls: list[ToolCall] = []
    text_chunks: list[str] = []

    output = getattr(response, "output", None) or []
    for item in output:
        item_type = _attr(item, "type")
        if item_type == "function_call":
            try:
                args = json.loads(_attr(item, "arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw_arguments": _attr(item, "arguments")}
            tool_calls.append(
                ToolCall(
                    id=_attr(item, "call_id") or _attr(item, "id") or "",
                    name=_attr(item, "name") or "",
                    args=args if isinstance(args, dict) else {"_value": args},
                )
            )
        elif item_type == "message":
            for c in _attr(item, "content") or []:
                if _attr(c, "type") in ("output_text", "text"):
                    text_chunks.append(_attr(c, "text") or "")

    text = "".join(text_chunks) or None
    is_final = bool(text) and not tool_calls
    stop_reason: StopReason
    if tool_calls:
        stop_reason = "tool_calls"
    elif is_final:
        stop_reason = "end_turn"
    else:
        stop_reason = "other"

    return ModelAction(
        is_final_answer=is_final,
        text=text,
        tool_calls=tool_calls,
        usage=_extract_usage(response),
        stop_reason=stop_reason,
        raw={"id": getattr(response, "id", None)},
    )


def _attr(obj: Any, name: str) -> Any:
    """Read a field from either a pydantic-style object or a plain dict.

    The SDK returns pydantic models in production but tests pass dicts; this
    keeps both paths working without forcing test fixtures to mock pydantic.
    """
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _extract_usage(response: Any) -> TokenUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage.empty()
    prompt = _attr(usage, "input_tokens") or 0
    completion = _attr(usage, "output_tokens") or 0
    total = _attr(usage, "total_tokens") or (prompt + completion)
    cached = 0
    details = _attr(usage, "input_tokens_details")
    if details is not None:
        cached = _attr(details, "cached_tokens") or 0
    return TokenUsage(prompt=prompt, completion=completion, cached=cached, total=total)


def _wrap_openai_error(e: Exception) -> AdapterError:
    """Map openai SDK errors to the adapter hierarchy.

    Import lazily so this module loads without `openai` installed for callers
    that just want the class for typing.
    """
    try:
        import openai
    except ImportError:
        return AdapterError(str(e))

    if isinstance(e, openai.RateLimitError):
        return AdapterRateLimitError(str(e))
    if isinstance(e, openai.AuthenticationError | openai.PermissionDeniedError):
        return AdapterAuthError(str(e))
    if isinstance(e, openai.APITimeoutError | openai.APIConnectionError):
        return TransientAdapterError(str(e))
    if isinstance(e, openai.APIStatusError):
        status = getattr(e, "status_code", 0) or 0
        if status >= 500:
            return TransientAdapterError(str(e))
        return AdapterError(str(e))
    return AdapterError(str(e))


__all__ = ["OpenAIAdapter"]
