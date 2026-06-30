"""ToolRegistry — per-Harness collection of tools, with profile filtering.

The registry is the source of truth for which tools exist in a `Harness`. It
holds `ToolSpec` instances and filters them by profile when a Session asks for
its tool surface. Profile semantics are derived from the `readonly` and
`pseudo` flags on each spec — `read_only` is "readonly tools + pseudo-tools",
`eval` is the same minus the two pseudo-tools that defeat determinism (oracle
escalation and clarification requests).

No module-level singleton: each `Harness` owns its own registry so multiple
harnesses can coexist in one process (tests, eval suites, multi-tenant servers).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, Literal

from reigner.tools.base import RunnableToolAdapter, ToolSpec

Profile = Literal["full", "read_only", "eval"]

_EVAL_EXCLUDED: frozenset[str] = frozenset({"escalate_to_oracle", "request_clarification"})
"""Pseudo-tools excluded from the `eval` profile because they break determinism:
oracle escalation introduces a different model; clarification pauses the loop.
"""


class ToolRegistrationError(ValueError):
    """Raised when a tool can't be registered (missing spec, name collision)."""


class ToolRegistry:
    """In-memory map of tool name → ToolSpec, scoped to one Harness.

    Construct empty, then `register` decorated functions or bare `ToolSpec`s.
    The Session asks for `for_profile(profile)` to get its tool surface for
    each call; nothing here mutates per-session state.
    """

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(
        self, func_or_spec: Callable[..., Any] | ToolSpec | RunnableToolAdapter
    ) -> ToolSpec:
        """Register a decorated function, a bare ToolSpec, or a RunnableToolAdapter.

        Returns the underlying spec.

        Raises ToolRegistrationError on:
            - a function without `__reigner_spec__` (forgot @tool)
            - a name already present in the registry
        """
        if isinstance(func_or_spec, ToolSpec):
            spec = func_or_spec
        elif isinstance(func_or_spec, RunnableToolAdapter):
            spec = func_or_spec.spec
        else:
            spec = _spec_of(func_or_spec)
        if spec.name in self._specs:
            raise ToolRegistrationError(
                f"tool {spec.name!r} is already registered — names must be unique."
            )
        self._specs[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec:
        """Look up a registered tool by name. KeyError if not present."""
        return self._specs[name]

    def schemas(self) -> list[dict[str, Any]]:
        """JSON Schema list for every registered tool, in insertion order.

        Provider-agnostic. Model adapters translate to provider-specific
        tool-schema shapes.
        """
        return [spec.json_schema() for spec in self._specs.values()]

    def for_profile(self, profile: Profile) -> list[RunnableToolAdapter]:
        """Return the tool subset visible under `profile` as adapters.

        full       — every registered tool.
        read_only  — readonly tools plus pseudo-tools.
        eval       — readonly tools plus pseudo-tools except `escalate_to_oracle`
                     and `request_clarification` (both defeat determinism).

        Adapters are constructed fresh on each call; with ~10 tools per harness
        the allocation cost is negligible. The loop wants `.run(args)`, so this
        is the call site that hands out runnables.
        """
        if profile == "full":
            specs: list[ToolSpec] = list(self._specs.values())
        elif profile == "read_only":
            specs = [s for s in self._specs.values() if s.readonly or s.pseudo]
        elif profile == "eval":
            specs = [
                s
                for s in self._specs.values()
                if (s.readonly or s.pseudo) and s.name not in _EVAL_EXCLUDED
            ]
        else:
            raise ValueError(f"unknown profile: {profile!r}")
        return [RunnableToolAdapter(spec=s) for s in specs]

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._specs

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)


def _spec_of(func: Callable[..., Any]) -> ToolSpec:
    """Extract the ToolSpec a decorated function carries, or raise a clear error."""
    spec = getattr(func, "__reigner_spec__", None)
    if not isinstance(spec, ToolSpec):
        raise ToolRegistrationError(
            f"{getattr(func, '__name__', func)!r} is not a @tool-decorated function — "
            "apply @tool(...) before registering, or pass a ToolSpec directly."
        )
    return spec


__all__ = [
    "Profile",
    "ToolRegistrationError",
    "ToolRegistry",
]
