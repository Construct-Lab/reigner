"""@tool decorator, ToolSpec, and ToolResult — the foundation of the tool system.

See SPEC.md §6 (Tool System) and PRINCIPLES.md §5 (MCP-clean by construction).

The decorator's role is intentionally narrow: validate the signature against
MCP-clean constraints at decoration time, generate the JSON Schema for the
model, and attach a ToolSpec to the function via `__reigner_spec__`. It does
not wrap or catch exceptions — the loop (T-05) owns exception → ErrorEvent
translation so tool failures stay visible in the event stream.

Tool results should be self-describing per PRINCIPLES.md §2 (bounded outputs):
`has_more`, `truncated`, `available_keys`, etc. The `ToolResult` alias here
documents that convention without enforcing a shape — different tools need
different self-description fields (see SPEC §6.4).
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import create_model

ToolResult = dict[str, Any]
"""Documented type alias for tool return values.

PRINCIPLES.md §2 calls for bounded, self-describing results (`has_more`,
`truncated`, `available_keys`). Not enforced as a class because the right
self-description fields vary by tool.
"""


F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


class ToolDefinitionError(TypeError):
    """Raised at decoration time when a function violates MCP-clean constraints."""


@dataclass(frozen=True, kw_only=True)
class ToolSpec:
    """Metadata + invocation handle for a registered tool.

    Structurally satisfies `harness.state.ToolSpec` Protocol — `name`,
    `description`, `readonly`, and `json_schema()` are the surface AgentState
    reads. The remaining flags (`cache`, `truncate_chars`, `pseudo`) are
    consumed by guardrails in T-06 and by profile filtering in the registry.
    """

    name: str
    description: str
    readonly: bool
    pseudo: bool
    cache: bool
    truncate_chars: int | None
    func: Callable[..., Awaitable[Any]]
    schema: dict[str, Any]

    def json_schema(self) -> dict[str, Any]:
        """JSON Schema for the tool's arguments. Surfaces in the model's tool list."""
        return self.schema

    async def call(self, **kwargs: Any) -> Any:
        """Invoke the wrapped tool function.

        Exceptions propagate. T-05 (the loop) wraps invocations and converts
        exceptions into `ErrorEvent` so failures stay observable.
        """
        return await self.func(**kwargs)


def tool(
    *,
    readonly: bool = False,
    cache: bool = False,
    truncate_chars: int | None = None,
    description: str | None = None,
    pseudo: bool = False,
) -> Callable[[F], F]:
    """Decorate an async function as a Reigner tool.

    Validates MCP-clean constraints at decoration time, generates a JSON Schema
    for the arguments via Pydantic, and attaches a `ToolSpec` to the function
    as `__reigner_spec__`. The original callable is returned unchanged — direct
    calls work in tests without going through the registry.

    Args mirror SPEC §6.1:
        readonly: eligible for G9 caching and G11 parallel execution.
        cache: opt-in result caching keyed on (name, args).
        truncate_chars: per-tool override of the G2 truncation budget.
        description: overrides the function's docstring on the tool schema.
        pseudo: intercepted locally by the loop (T-08); implies `readonly=True`.
    """

    def decorator(func: F) -> F:
        _validate_signature(func, pseudo=pseudo, readonly=readonly)
        spec = ToolSpec(
            name=func.__name__,
            description=description or (inspect.getdoc(func) or ""),
            readonly=readonly,
            pseudo=pseudo,
            cache=cache,
            truncate_chars=truncate_chars,
            func=func,
            schema=_build_args_schema(func),
        )
        func.__reigner_spec__ = spec  # type: ignore[attr-defined]
        return func

    return decorator


def _validate_signature(
    func: Callable[..., Any],
    *,
    pseudo: bool,
    readonly: bool,
) -> None:
    """Enforce MCP-clean constraints. PRINCIPLES.md §5 + SPEC §22 line 1240."""
    name = func.__name__
    if not inspect.iscoroutinefunction(func):
        raise ToolDefinitionError(
            f"@tool {name}: must be `async def` — sync tools are not supported."
        )
    if pseudo and not readonly:
        raise ToolDefinitionError(
            f"@tool {name}: pseudo=True requires readonly=True "
            "(pseudo-tools are intercepted locally and never mutate external state)."
        )
    sig = inspect.signature(func)
    for pname, param in sig.parameters.items():
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            raise ToolDefinitionError(
                f"@tool {name}: **{pname} is not allowed — tools must declare every "
                "parameter so the JSON schema is complete."
            )
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            raise ToolDefinitionError(
                f"@tool {name}: *{pname} is not allowed — tools are called by keyword."
            )
        if param.kind is inspect.Parameter.POSITIONAL_ONLY:
            raise ToolDefinitionError(
                f"@tool {name}: positional-only parameter {pname!r} is not allowed — "
                "MCP tools are invoked by keyword."
            )
        if param.annotation is inspect.Parameter.empty:
            raise ToolDefinitionError(
                f"@tool {name}: parameter {pname!r} is missing a type annotation."
            )


def _build_args_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Build a JSON Schema for the function's arguments via Pydantic.

    `pydantic.create_model` handles unions, Literals, optionals, list/dict
    types, and defaults uniformly. Failures here mean an annotation can't be
    represented in JSON Schema — surfaced as a `ToolDefinitionError` so the
    author finds it at decoration time, not when the model first calls the tool.
    """
    sig = inspect.signature(func)
    fields: dict[str, Any] = {}
    for pname, param in sig.parameters.items():
        default = param.default if param.default is not inspect.Parameter.empty else ...
        fields[pname] = (param.annotation, default)
    try:
        model = create_model(f"{func.__name__}__args", **fields)
    except Exception as exc:
        raise ToolDefinitionError(
            f"@tool {func.__name__}: failed to build JSON schema for arguments — {exc}"
        ) from exc
    schema: dict[str, Any] = model.model_json_schema()
    return schema


@dataclass(frozen=True)
class RunnableToolAdapter:
    """Lifts a ``@tool``-decorated function into the loop's RunnableTool Protocol.

    The decorator returns the bare function with ``__reigner_spec__`` attached;
    the loop reads flat ``.name`` / ``.readonly`` / ``.json_schema()`` and calls
    ``.run(args)``. This adapter is the single bridge for every tool collection
    (artifacts, search, future domain tools) so they don't each invent their own.
    """

    spec: ToolSpec

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def description(self) -> str:
        return self.spec.description

    @property
    def readonly(self) -> bool:
        return self.spec.readonly

    @property
    def pseudo(self) -> bool:
        return self.spec.pseudo

    @property
    def cache(self) -> bool:
        return self.spec.cache

    @property
    def truncate_chars(self) -> int | None:
        return self.spec.truncate_chars

    def json_schema(self) -> dict[str, Any]:
        return self.spec.json_schema()

    async def run(self, args: dict[str, Any]) -> Any:
        return await self.spec.func(**args)


def to_runnable(func: Callable[..., Awaitable[Any]]) -> RunnableToolAdapter:
    """Wrap a ``@tool``-decorated callable as a ``RunnableToolAdapter``.

    Raises ``ToolDefinitionError`` if ``func`` lacks ``__reigner_spec__`` — the
    marker the ``@tool`` decorator attaches at decoration time.
    """
    spec = getattr(func, "__reigner_spec__", None)
    if not isinstance(spec, ToolSpec):
        raise ToolDefinitionError(
            f"{getattr(func, '__name__', func)!r} is not a @tool-decorated callable"
        )
    return RunnableToolAdapter(spec=spec)


__all__ = [
    "RunnableToolAdapter",
    "ToolDefinitionError",
    "ToolResult",
    "ToolSpec",
    "to_runnable",
    "tool",
]
