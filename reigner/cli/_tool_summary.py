"""Derive one-line, self-describing summaries from bounded tool results.

Pure functions with no rich/console dependency so they stay trivially testable.
Reigner's tool results are already bounded and self-describing (``has_more``,
``truncated``, ``available_keys``, and list fields like ``hits`` / ``matches``),
so a small set of heuristics over those shapes produces an informative line
without every tool having to declare its own view. (Tools declaring their own
``render()`` is the cleaner long-term shape — deferred behind this renderer.)

Nothing here raises: an unknown result shape falls back to a type/length note
rather than blowing up the transcript.
"""

from __future__ import annotations

from typing import Any

# Result keys whose value is a list of returned items, rendered as "N label".
_COUNT_KEYS: tuple[tuple[str, str], ...] = (
    ("hits", "hits"),
    ("matches", "matches"),
    ("rows", "rows"),
    ("entities", "entities"),
    ("entries", "entries"),
    ("paths", "paths"),
)

# Result keys carrying a byte / character size, rendered via _human_bytes.
_SIZE_KEYS: tuple[str, ...] = ("bytes", "total_size", "size")

# Args worth showing bare (in quotes) as the primary subject of a call, and the
# order we prefer them in when a call carries more than one.
_PRIMARY_ARG_KEYS: tuple[str, ...] = (
    "query",
    "pattern",
    "q",
    "text",
    "artifact_id",
    "section",
    "path",
    "file_path",
)

# Args that are pure noise in a one-liner: falsy defaults the model didn't set
# meaningfully. Dropped whole — never clipped mid-token.
_NOISE_DEFAULTS: dict[str, Any] = {"offset": 0}


def _human_bytes(n: int) -> str:
    """Render a byte count compactly: 812 B, 1.8 KB, 4.0 KB, 2.1 MB."""
    if n < 1024:
        return f"{n} B"
    kb = n / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    return f"{kb / 1024:.1f} MB"


def summarise(name: str, result: Any, *, truncated: bool) -> str:
    """One-line, self-describing summary of a tool result.

    Never raises — unknown shapes fall back to a type/length note. ``truncated``
    is surfaced explicitly (with the extra keys the model can still fetch) so a
    dropped result is visible rather than silently short.

    Args:
        name: Tool name (reserved for future tool-specific tweaks; unused today).
        result: The raw tool result — typically a bounded dict, sometimes a str.
        truncated: Whether the harness truncated this result before the model saw it.

    Returns:
        A ``" · "``-joined summary, e.g. ``"5 hits"`` or ``"4.0 KB · truncated"``.
    """
    parts: list[str] = []
    if isinstance(result, dict):
        for key, label in _COUNT_KEYS:
            seq = result.get(key)
            if isinstance(seq, list):
                parts.append(f"{len(seq)} {label}")
        for key in _SIZE_KEYS:
            nbytes = result.get(key)
            if isinstance(nbytes, bool):  # bool is an int subclass — skip flags
                continue
            if isinstance(nbytes, int | float):
                parts.append(_human_bytes(int(nbytes)))
                break
        else:
            content = result.get("content")
            if isinstance(content, str):
                parts.append(_human_bytes(len(content.encode())))
        if result.get("has_more"):
            parts.append("more available")
    elif isinstance(result, str):
        parts.append(_human_bytes(len(result.encode())))

    if truncated:
        keys = result.get("available_keys") if isinstance(result, dict) else None
        parts.append("truncated" + (f" · +{keys}" if keys else ""))

    return " · ".join(parts) or "ok"


def _clip(text: str, limit: int) -> str:
    """Clip a string at a value boundary with an ellipsis — never mid-token."""
    text = text.replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _fmt_scalar(value: Any) -> str:
    if isinstance(value, str):
        return _clip(value, 24)
    return repr(value)


def clean_args(args: dict[str, Any], *, max_len: int = 64) -> str:
    """Render call args to a compact, noise-free line.

    Drops ``None`` / empty values and falsy defaults (``offset=0``) whole rather
    than clipping them mid-token. A primary subject arg (query / pattern / path)
    is shown bare in quotes; the rest render as ``key=value`` pairs.

    Args:
        args: The tool call's argument dict.
        max_len: Soft cap on the rendered length before a trailing ellipsis.

    Returns:
        A ``" · "``-joined argument line, possibly empty.
    """
    parts: list[str] = []
    primary_key: str | None = None
    for key in _PRIMARY_ARG_KEYS:
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(f'"{_clip(val, 40)}"')
            primary_key = key
            break

    for key, val in args.items():
        if key == primary_key:
            continue
        if val is None or val == "" or val == [] or val == {}:
            continue
        if key in _NOISE_DEFAULTS and val == _NOISE_DEFAULTS[key]:
            continue
        parts.append(f"{key}={_fmt_scalar(val)}")

    joined = " · ".join(parts)
    if len(joined) > max_len:
        joined = joined[: max_len - 1].rstrip() + "…"
    return joined


__all__ = ["clean_args", "summarise"]
