"""Gemini adapter via the `google-genai` SDK.

v0 does not use Gemini's explicit `CachedContent` API — the stable prefix is
re-sent inline each call. `supports_prompt_caching=False` reflects that. The
plumbing for explicit caching is a follow-up; not required to ship the loop.

Gemini's schema validator rejects a handful of JSON Schema keywords; the
boundary cleanup lives in `base.render_tool_for_gemini`.
"""

from __future__ import annotations

import base64
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
    render_tool_for_gemini,
)
from reigner.harness.state import Prompt, ToolSpec, Turn
from reigner.types import EffortLevel

if TYPE_CHECKING:
    from google.genai import Client

# thinking_level tops out at "high"; reigner's higher tiers clamp down. Gemini's
# "minimal" has no reigner equivalent, so it is never emitted.
_THINKING: dict[EffortLevel, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",
    "max": "high",
}


def _supports_thinking(model: str) -> bool:
    """True for Gemini models that take ``thinking_config.thinking_level``.

    Only the 3.x/3.5 family accepts ``thinking_level`` on the ``generateContent``
    API — Gemini 2.5 rejects it with a 400 ("Thinking level is not supported for
    this model"; 2.5 uses the numeric ``thinking_budget``, which reigner does not
    wire). 2.5 and older therefore get no effort and run at their provider
    default; ``temperature`` may still be set on them (they accept it).
    """
    return model.startswith("gemini-3")


@dataclass
class GeminiAdapter:
    """Model adapter for Google Gemini via the ``google-genai`` SDK."""

    model: str = "gemini-2.0-flash"
    api_key: str | None = None
    effort: EffortLevel = "medium"
    temperature: float | None = None
    name: str = "gemini"
    supports_prompt_caching: bool = False

    _client: Client | None = None

    def _get_client(self) -> Client:
        if self._client is not None:
            return self._client
        try:
            from google import genai
        except ImportError as e:
            raise AdapterError(
                "google-genai package not installed. Install with `pip install reigner[gemini]`."
            ) from e
        kwargs: dict[str, Any] = {}
        if self.api_key is not None:
            kwargs["api_key"] = self.api_key
        self._client = genai.Client(**kwargs)
        return self._client

    async def call(self, prompt: Prompt, tools: list[ToolSpec]) -> ModelAction:
        """Call Gemini with the prompt and tools, returning a ModelAction.

        Args:
            prompt: The harness prompt (stable prefix + turns).
            tools: Tool specs to expose to the model this turn.

        Returns:
            The provider response normalized into a :class:`ModelAction`.
        """
        client = self._get_client()
        config: dict[str, Any] = {"system_instruction": prompt.stable}
        if _supports_thinking(self.model):
            config["thinking_config"] = {"thinking_level": _THINKING[self.effort]}
        elif self.temperature is not None:
            # Pre-2.5 models: temperature only, and only when explicitly set.
            config["temperature"] = self.temperature
        if tools:
            config["tools"] = [
                {"function_declarations": [render_tool_for_gemini(t) for t in tools]}
            ]

        try:
            # The genai SDK accepts a plain dict for config at runtime, but its
            # type stubs require GenerateContentConfig. We pass dict for clarity
            # and ignore the static mismatch.
            response = await client.aio.models.generate_content(
                model=self.model,
                contents=_turns_to_contents(prompt.messages),
                config=config,  # type: ignore[arg-type]
            )
        except Exception as e:  # noqa: BLE001
            raise _wrap_gemini_error(e) from e

        return _parse_response(response)


def _turns_to_contents(turns: list[Turn]) -> list[dict[str, Any]]:
    """Translate Turns into Gemini Content dicts.

    Gemini uses roles ``user`` and ``model`` (not ``assistant``) and packs all
    parts of a turn into a single Content's `parts` list. Tool calls are
    `function_call` parts on a model turn; tool results are
    `function_response` parts on a user turn.
    """
    contents: list[dict[str, Any]] = []
    for t in turns:
        if t.role == "tool":
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "function_response": {
                                # Gemini keys responses by tool name, not call id —
                                # callers should ensure the prior model turn's
                                # function_call carried this name.
                                "name": _tool_name_from_call_id(t.tool_call_id, turns),
                                "response": {"content": t.content},
                            }
                        }
                    ],
                }
            )
            continue
        if t.role == "assistant" and t.tool_calls:
            parts: list[dict[str, Any]] = []
            if t.content:
                parts.append({"text": t.content})
            for call in t.tool_calls:
                part: dict[str, Any] = {
                    "function_call": {
                        "name": call.get("name", ""),
                        "args": call.get("args", {}),
                    }
                }
                # Echo the thought_signature back (decoded to bytes) so Gemini 3.x
                # accepts the replayed function call.
                sig = call.get("signature")
                if sig:
                    part["thought_signature"] = base64.b64decode(sig)
                parts.append(part)
            contents.append({"role": "model", "parts": parts})
            continue
        role = "model" if t.role == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": t.content}]})
    return contents


def _tool_name_from_call_id(call_id: str | None, turns: list[Turn]) -> str:
    """Resolve a tool-call id back to its tool name.

    Gemini's `function_response` is keyed by name; the rest of the harness
    threads results by `call_id`. We look back through history to find the
    `tool_call` with this id and return its name. Fallback: empty string —
    Gemini will reject it, surfacing the issue loudly.
    """
    if not call_id:
        return ""
    for t in turns:
        for call in t.tool_calls or []:
            if call.get("id") == call_id:
                return str(call.get("name", ""))
    return ""


def _parse_response(response: Any) -> ModelAction:
    tool_calls: list[ToolCall] = []
    text_chunks: list[str] = []
    raw_stop = ""

    candidates = getattr(response, "candidates", None) or []
    if candidates:
        cand = candidates[0]
        raw_stop = str(_attr(cand, "finish_reason") or "")
        content = _attr(cand, "content")
        for part in _attr(content, "parts") or []:
            fc = _attr(part, "function_call")
            if fc is not None:
                args = _attr(fc, "args") or {}
                # Gemini 3.x attaches a thought_signature (bytes) to the part; it
                # must be replayed on the next request or the follow-up turn 400s.
                raw_sig = _attr(part, "thought_signature")
                signature = (
                    base64.b64encode(raw_sig).decode("ascii")
                    if isinstance(raw_sig, (bytes, bytearray))
                    else None
                )
                tool_calls.append(
                    ToolCall(
                        id=_attr(fc, "id") or _synth_id(_attr(fc, "name") or ""),
                        name=_attr(fc, "name") or "",
                        args=dict(args) if isinstance(args, dict) else {"_value": args},
                        signature=signature,
                    )
                )
                continue
            text = _attr(part, "text")
            if text:
                text_chunks.append(text)

    text = "".join(text_chunks) or None
    stop_reason: StopReason
    if tool_calls:
        stop_reason = "tool_calls"
    elif raw_stop in ("STOP", "FinishReason.STOP"):
        stop_reason = "end_turn"
    elif raw_stop in ("MAX_TOKENS", "FinishReason.MAX_TOKENS"):
        stop_reason = "max_tokens"
    else:
        stop_reason = "other"

    is_final = stop_reason == "end_turn" and bool(text) and not tool_calls

    return ModelAction(
        is_final_answer=is_final,
        text=text,
        tool_calls=tool_calls,
        usage=_extract_usage(response),
        stop_reason=stop_reason,
        raw={"finish_reason": raw_stop},
    )


_FC_COUNTER = 0


def _synth_id(name: str) -> str:
    """Synthesize a call id for providers that don't return one.

    Gemini's `function_call` parts don't carry a call id in the SDK response;
    we mint a deterministic-enough one so the harness can route the result
    back. Threaded back as the response's `name` (see `_tool_name_from_call_id`).
    """
    global _FC_COUNTER
    _FC_COUNTER += 1
    return f"gemini-{name}-{_FC_COUNTER}"


def _attr(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _extract_usage(response: Any) -> TokenUsage:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return TokenUsage.empty()
    prompt_tokens = _attr(usage, "prompt_token_count") or 0
    visible = _attr(usage, "candidates_token_count") or 0
    # Thinking tokens are billed at the output rate ("output including thinking")
    # but reported separately, so fold them into completion or cost undercounts.
    thoughts = _attr(usage, "thoughts_token_count") or 0
    completion = visible + thoughts
    total = _attr(usage, "total_token_count") or (prompt_tokens + completion)
    cache_read = _attr(usage, "cached_content_token_count") or 0
    # Gemini's `prompt_token_count` includes cached content; subtract it so
    # `prompt` is fresh input. Cache writes aren't billed per-token here.
    prompt = max(prompt_tokens - cache_read, 0)
    return TokenUsage(
        prompt=prompt,
        completion=completion,
        cached=cache_read,
        cache_read=cache_read,
        total=total,
    )


def _wrap_gemini_error(e: Exception) -> AdapterError:
    """Map google-genai errors to the adapter hierarchy.

    google-genai surfaces a single `APIError` with `code` and `status`. We
    branch on the HTTP code; transient = 429 / 5xx.
    """
    try:
        from google.genai import errors as genai_errors
    except ImportError:
        return AdapterError(str(e))

    if isinstance(e, genai_errors.APIError):
        code = getattr(e, "code", 0) or 0
        if code == 429:
            return AdapterRateLimitError(str(e))
        if code in (401, 403):
            return AdapterAuthError(str(e))
        if code >= 500:
            return TransientAdapterError(str(e))
        return AdapterError(str(e))
    return AdapterError(str(e))


__all__ = ["GeminiAdapter"]
