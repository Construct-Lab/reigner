"""Adapter protocol and provider-neutral return types.

The loop reads `action.is_final_answer`, `action.tool_calls`, and `action.text`
off whatever adapter is wired in.

Design choices:

- Single-shot `async call(...) -> ModelAction`. No token streaming in v0; the
  event stream the harness yields is driven by tool-call boundaries, not by
  per-token deltas. A streaming variant can be added later without changing
  this Protocol.
- `ToolSpec.json_schema()` returns the *inner* object schema only
  (``{"type": "object", "properties": {...}, "required": [...]}``); each
  adapter wraps it in the provider envelope (`parameters` for OpenAI/Gemini,
  `input_schema` for Anthropic). Keeps tools provider-agnostic and MCP-clean.
- `TokenUsage` is required on every response. Providers that don't report a
  field fill it with 0 — we'd rather propagate zeros than `None` through the
  cost reporting path.
- No retries inside adapters. Transient errors get wrapped in
  `TransientAdapterError` so a future retry layer (or the loop's nudge logic)
  can decide policy. Adapters stay thin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from reigner.harness.state import Prompt, ToolSpec

StopReason = Literal["tool_calls", "end_turn", "max_tokens", "stop_sequence", "other"]


# ---------------------------------------------------------------------------
# Return shapes
# ---------------------------------------------------------------------------


@dataclass(kw_only=True, frozen=True)
class ToolCall:
    """Provider-neutral tool call as the loop sees it.

    `id` is the provider-supplied call identifier (used to thread the matching
    tool result back in the next turn). `args` is already JSON-decoded.
    """

    id: str
    name: str
    args: dict[str, Any]


@dataclass(kw_only=True, frozen=True)
class TokenUsage:
    """Token accounting for one model call.

    Fields are best-effort: providers that don't report a field set it to 0.

    - `prompt` is the *fresh* (non-cached) input tokens billed at the full input
      rate. Adapters normalise to this: Anthropic already reports uncached input
      in `input_tokens`; OpenAI/Gemini include cached tokens in their input
      count, so those adapters subtract the cached portion out.
    - `cache_read` / `cache_write` are cached input tokens served from / written
      to the provider's prompt cache. They bill at different rates (see
      `reigner.pricing`), so they are tracked separately for accurate cost.
    - `cached` = `cache_read + cache_write`, kept as a back-compat convenience.
    - `total` is the provider's reported total when available, otherwise
      ``prompt + completion``.
    """

    prompt: int = 0
    completion: int = 0
    cached: int = 0
    cache_read: int = 0
    cache_write: int = 0
    total: int = 0

    @classmethod
    def empty(cls) -> TokenUsage:
        """Return a zeroed :class:`TokenUsage`."""
        return cls()

    def __add__(self, other: object) -> TokenUsage:
        """Sum two usages field-wise, so a run can accumulate per-call totals."""
        if not isinstance(other, TokenUsage):
            return NotImplemented
        return TokenUsage(
            prompt=self.prompt + other.prompt,
            completion=self.completion + other.completion,
            cached=self.cached + other.cached,
            cache_read=self.cache_read + other.cache_read,
            cache_write=self.cache_write + other.cache_write,
            total=self.total + other.total,
        )


@dataclass(kw_only=True, frozen=True)
class ModelAction:
    """What `ModelAdapter.call` returns; what the loop branches on.

    Exactly one of (`is_final_answer=True` with `text`) or
    (`tool_calls != []`) is the normal path. A response with neither — empty
    text and no tool calls — is unusual; the loop should treat it as a
    no-progress turn and let the iteration nudge (G3) fire.
    """

    is_final_answer: bool
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage.empty)
    stop_reason: StopReason = "other"
    raw: dict[str, Any] = field(default_factory=dict)
    """Provider response passthrough for debugging and plugin inspection.
    Adapters MAY store the raw response here; consumers must not rely on its
    shape across providers."""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AdapterError(Exception):
    """Base class for adapter-layer failures.

    Adapters wrap provider SDK errors into this hierarchy so the loop can
    classify failures without importing every SDK. The original exception is
    preserved on `__cause__`.
    """


class TransientAdapterError(AdapterError):
    """Likely retryable: rate limits, 5xx, timeouts, transient network errors.

    A retry policy upstairs can back off and try again. Adapters themselves
    never retry.
    """


class AdapterRateLimitError(TransientAdapterError):
    """Provider rate limit (HTTP 429).

    Subclass of transient so generic retry handlers catch it, but distinguished
    for backoff tuning.
    """


class AdapterAuthError(AdapterError):
    """Auth/permissions failure (HTTP 401/403). Not retryable — fail fast."""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ModelAdapter(Protocol):
    """The contract the harness loop depends on.

    Concrete adapters live in sibling modules and are lazy in their SDK
    imports so users only pay for the providers they install.
    """

    name: str
    """Stable short identifier: ``"openai"`` / ``"anthropic"`` / ``"gemini"``.
    Surfaces in events (e.g. OracleEscalationEvent) and session metadata."""

    model: str
    """Provider-specific model id (e.g. ``"gpt-4o-mini"``,
    ``"claude-opus-4-7"``, ``"gemini-2.0-flash"``)."""

    supports_prompt_caching: bool
    """True if the provider honours the stable/dynamic split in Prompt (G1)
    such that the stable preamble is actually cached. Used by plugins/metrics
    to label cache_hit ratios meaningfully."""

    async def call(self, prompt: Prompt, tools: list[ToolSpec]) -> ModelAction:
        """Send one request, return the parsed action.

        Adapters must:

        1. Translate `prompt.stable` into the provider's system / cached prefix
           slot.
        2. Translate `prompt.messages` (`Turn` records) into the provider's
           message list, threading prior tool_use/tool_result pairs correctly.
        3. Translate each `tool.json_schema()` into the provider tool envelope.
        4. Parse the response into a `ModelAction`, populating `tool_calls`
           when present, `text` + `is_final_answer=True` for terminal text
           responses, and `usage` from whatever counters the provider returns.
        5. Wrap SDK errors into the `AdapterError` hierarchy. Never retry.
        """
        ...


# ---------------------------------------------------------------------------
# Translation helpers shared across adapters
# ---------------------------------------------------------------------------


def render_tool_for_openai(tool: ToolSpec) -> dict[str, Any]:
    """OpenAI Responses-API shape.

    Uses the flat Responses form (``{"type": "function", "name": ...,
    "parameters": ...}``) rather than the older Chat Completions wrapper
    (``{"type": "function", "function": {...}}``). `strict: True` opts into
    schema-conformant tool arg generation — aligns with the bounded-output
    discipline.

    Strict mode imposes JSON Schema rules Pydantic's default output violates
    (``additionalProperties: false`` on every object, every property listed in
    ``required``, no ``default``). Normalize at the boundary so tool authors
    keep writing canonical JSON Schema — same pattern as
    ``_strip_gemini_unsupported``.

    Some legitimate tools take open-ended arguments (``Any`` values, ``dict[
    str, Any]`` locators — e.g. ``register_citation``) which strict mode simply
    cannot represent: it requires every leaf to declare a ``type`` and every
    object to be closed. For those, fall back to the unnormalized schema with
    ``strict: False`` rather than crashing every chat turn.
    """
    raw = tool.json_schema()
    if _is_openai_strict_compatible(raw):
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": _normalize_openai_strict(raw),
            "strict": True,
        }
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": raw,
        "strict": False,
    }


def render_tool_for_anthropic(tool: ToolSpec) -> dict[str, Any]:
    """Anthropic tool shape — note `input_schema`, not `parameters`."""
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.json_schema(),
    }


def render_tool_for_gemini(tool: ToolSpec) -> dict[str, Any]:
    """Gemini function-declaration shape.

    Gemini rejects a handful of JSON Schema keywords (`additionalProperties`,
    `$schema`, `$defs`, `definitions`); strip them at the boundary so tools
    can return canonical JSON Schema and stay portable.
    """
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": _strip_gemini_unsupported(tool.json_schema()),
    }


_GEMINI_UNSUPPORTED_KEYS = frozenset(
    {"additionalProperties", "$schema", "$defs", "definitions", "$id"}
)


def _strip_gemini_unsupported(schema: Any) -> Any:
    """Recursively remove keys Gemini's schema validator rejects."""
    if isinstance(schema, dict):
        return {
            k: _strip_gemini_unsupported(v)
            for k, v in schema.items()
            if k not in _GEMINI_UNSUPPORTED_KEYS
        }
    if isinstance(schema, list):
        return [_strip_gemini_unsupported(v) for v in schema]
    return schema


def _normalize_openai_strict(schema: Any) -> Any:
    """Recursively coerce a JSON Schema into OpenAI strict-mode compliance.

    Strict mode (``tools[*].strict = true``) requires:
    - every object schema declares ``additionalProperties: false``
    - every key in ``properties`` is listed in ``required``
    - ``default`` is rejected (the model is expected to always supply a value;
      optional-ness is expressed by unioning with ``null``, which Pydantic
      already emits for ``T | None`` parameters)

    Pydantic's ``model_json_schema()`` emits none of these by default, so we
    massage the schema at the OpenAI boundary instead of forcing every tool
    author to write strict-mode-shaped schemas. The walk descends into
    ``properties``, ``$defs``, ``items``, and ``anyOf`` / ``oneOf`` / ``allOf``
    branches so nested object schemas (Pydantic ``$ref``-ed models) are
    normalized too.
    """
    if isinstance(schema, dict):
        out = {k: _normalize_openai_strict(v) for k, v in schema.items() if k != "default"}
        if "properties" in out or out.get("type") == "object":
            out["additionalProperties"] = False
            props = out.get("properties")
            if isinstance(props, dict):
                out["required"] = list(props.keys())
        return out
    if isinstance(schema, list):
        return [_normalize_openai_strict(v) for v in schema]
    return schema


_STRICT_SCHEMA_POSITIONS = ("items", "additionalItems", "not", "if", "then", "else")
_STRICT_SCHEMA_LIST_POSITIONS = ("anyOf", "oneOf", "allOf", "prefixItems")
_STRICT_SCHEMA_DICT_POSITIONS = ("properties", "$defs", "definitions")


def _is_openai_strict_compatible(schema: Any) -> bool:
    """Whether `schema` can be sent to OpenAI under ``strict: True``.

    Strict mode rejects two shapes Pydantic emits for genuinely-open arguments:
    a property with no concrete ``type`` (what ``Any`` becomes) and an object
    with ``additionalProperties: true`` or no declared ``properties`` (what
    ``dict[str, Any]`` becomes). Walk only schema positions — not every dict
    value — so titles, descriptions, and other annotation strings don't get
    misread as schemas.
    """
    if not isinstance(schema, dict):
        return True
    is_typed = any(
        k in schema for k in ("type", "$ref", "anyOf", "oneOf", "allOf", "enum", "const")
    )
    if not is_typed:
        return False
    if schema.get("type") == "object":
        if schema.get("additionalProperties") is True:
            return False
        if "properties" not in schema and schema.get("additionalProperties") is not False:
            return False
    for key in _STRICT_SCHEMA_POSITIONS:
        if key in schema and not _is_openai_strict_compatible(schema[key]):
            return False
    for key in _STRICT_SCHEMA_LIST_POSITIONS:
        branches = schema.get(key)
        if isinstance(branches, list) and not all(
            _is_openai_strict_compatible(b) for b in branches
        ):
            return False
    for key in _STRICT_SCHEMA_DICT_POSITIONS:
        children = schema.get(key)
        if isinstance(children, dict) and not all(
            _is_openai_strict_compatible(v) for v in children.values()
        ):
            return False
    return True


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
    "render_tool_for_anthropic",
    "render_tool_for_gemini",
    "render_tool_for_openai",
]
