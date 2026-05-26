"""Typed event protocol shared by the harness, sessions, plugins, and transports.

See SPEC.md §5.2. Events are inert dataclasses: the loop yields them, sessions
persist them as JSONL, plugins observe them, and transports (CLI/web/MCP) render
them. This module owns the shape and the wire format only — emission, storage,
and rendering live in their respective tasks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar

SCHEMA_VERSION = 2  # 2 adds UserQueryEvent (T-25 — sessions must record the query)


class UnknownEventType(ValueError):
    """Raised when from_json encounters a `type` not in EVENT_TYPES."""


class SchemaVersionMismatch(ValueError):
    """Raised by session loaders when a stored schema version != SCHEMA_VERSION."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(kw_only=True)
class Event:
    """Base for every event in the protocol.

    Envelope fields are common to all events so sessions can order, replay, and
    timestamp without re-wrapping. Subclasses set `type` as a ClassVar and add
    their own payload fields.
    """

    type: ClassVar[str] = ""
    seq: int
    session_id: str
    turn: int
    ts: datetime = field(default_factory=_utcnow)


@dataclass(kw_only=True)
class UserQueryEvent(Event):
    """The query that opened a conversational round.

    Emitted by ``Session.run_stream`` before the loop runs (the loop itself
    never sees the raw query as an event). This is the durable record of what
    the user asked: without it a session's JSONL has the agent's actions but
    not the question, so reconstruction/fork/replay (T-25) would be impossible.
    It also marks the round boundary `at_turn` counts against.
    """

    type: ClassVar[str] = "user_query"
    query: str


@dataclass(kw_only=True)
class StatusEvent(Event):
    type: ClassVar[str] = "status"
    message: str


@dataclass(kw_only=True)
class ToolCallEvent(Event):
    type: ClassVar[str] = "tool_call"
    name: str
    args: dict[str, Any]
    call_id: str


@dataclass(kw_only=True)
class ToolResultEvent(Event):
    type: ClassVar[str] = "tool_result"
    call_id: str
    result: Any
    truncated: bool
    cached: bool


@dataclass(kw_only=True)
class CitationEvent(Event):
    type: ClassVar[str] = "citation"
    source: str
    locator: dict[str, Any]
    value: Any


@dataclass(kw_only=True)
class ClarificationEvent(Event):
    type: ClassVar[str] = "clarification"
    question: str
    candidates: list[Any]


@dataclass(kw_only=True)
class FinalAnswerEvent(Event):
    type: ClassVar[str] = "final_answer"
    text: str
    metadata: dict[str, Any]


@dataclass(kw_only=True)
class ErrorEvent(Event):
    type: ClassVar[str] = "error"
    error: str
    recoverable: bool


@dataclass(kw_only=True)
class CompactionEvent(Event):
    type: ClassVar[str] = "compaction"
    level: int
    tokens_freed: int


@dataclass(kw_only=True)
class OracleEscalationEvent(Event):
    type: ClassVar[str] = "oracle"
    reason: str
    from_model: str
    to_model: str


@dataclass(kw_only=True)
class SteeringAcceptedEvent(Event):
    type: ClassVar[str] = "steering"
    message: str
    mode: str


_ALL_EVENT_CLASSES: tuple[type[Event], ...] = (
    UserQueryEvent,
    StatusEvent,
    ToolCallEvent,
    ToolResultEvent,
    CitationEvent,
    ClarificationEvent,
    FinalAnswerEvent,
    ErrorEvent,
    CompactionEvent,
    OracleEscalationEvent,
    SteeringAcceptedEvent,
)

EVENT_TYPES: dict[str, type[Event]] = {cls.type: cls for cls in _ALL_EVENT_CLASSES}


def _to_jsonable(value: Any, *, path: str) -> Any:
    """Recursively convert a value to JSON-coercible primitives.

    Strict: anything that isn't a JSON-native type (or datetime) raises
    TypeError naming the offending field path. Tool results must be coercible
    so sessions can round-trip; this is the enforcement point.
    """
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise TypeError(f"{path}: dict key {k!r} is not a string")
            out[k] = _to_jsonable(v, path=f"{path}.{k}")
        return out
    if isinstance(value, list | tuple):
        return [_to_jsonable(v, path=f"{path}[{i}]") for i, v in enumerate(value)]
    raise TypeError(
        f"{path}: value of type {type(value).__name__} is not JSON-coercible. "
        f"Tool results and event fields must be primitives, lists, dicts, or datetimes."
    )


def to_json(event: Event) -> str:
    """Serialize an event to a single JSON line.

    Raises TypeError if any field contains a non-JSON-coercible value, naming
    the path so the offending tool result is easy to find.
    """
    if not is_dataclass(event):
        raise TypeError(f"expected an Event dataclass, got {type(event).__name__}")
    payload: dict[str, Any] = {"type": event.type}
    for f in fields(event):
        payload[f.name] = _to_jsonable(getattr(event, f.name), path=f.name)
    return json.dumps(payload, separators=(",", ":"))


def from_json(line: str) -> Event:
    """Deserialize a JSON line into the matching Event subclass.

    Raises UnknownEventType if `type` is missing or not in EVENT_TYPES.
    """
    raw = json.loads(line)
    if not isinstance(raw, dict):
        raise UnknownEventType(f"expected a JSON object, got {type(raw).__name__}")
    type_name = raw.pop("type", None)
    if not isinstance(type_name, str):
        raise UnknownEventType("event JSON missing string 'type' field")
    cls = EVENT_TYPES.get(type_name)
    if cls is None:
        raise UnknownEventType(f"unknown event type: {type_name!r}")
    if "ts" in raw and isinstance(raw["ts"], str):
        raw["ts"] = datetime.fromisoformat(raw["ts"])
    return cls(**raw)


__all__ = [
    "EVENT_TYPES",
    "SCHEMA_VERSION",
    "CitationEvent",
    "ClarificationEvent",
    "CompactionEvent",
    "ErrorEvent",
    "Event",
    "FinalAnswerEvent",
    "OracleEscalationEvent",
    "SchemaVersionMismatch",
    "StatusEvent",
    "SteeringAcceptedEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "UnknownEventType",
    "UserQueryEvent",
    "from_json",
    "to_json",
]
