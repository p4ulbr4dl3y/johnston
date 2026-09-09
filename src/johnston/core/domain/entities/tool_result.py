"""Domain entities for tool execution results."""
import inspect
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class ToolResultStatus(str, Enum):
    """Canonical lifecycle status of a tool execution.

    ``str``-subclassed for direct JSON/string serialization.
    """

    DONE = "done"
    ERROR = "error"
    RUNNING = "running"
    CANCELLED = "cancelled"


@dataclass
class ToolResultEvent:
    """Structured payload of a ``tool_result`` stream event.

    Decouples consumers from the positional tuple protocol (``step[3:]``) so the
    tool-result fields are parsed once in :func:`parse_tool_result_step`.
    ``status`` is ``None`` when the stream tuple omits it (short fixtures).
    """

    content: str = ""
    is_error: bool = False
    status: Optional[ToolResultStatus] = None
    returncode: Optional[int] = None
    task_id: Optional[str] = None
    background_task_id: Optional[str] = None
    log_path: Optional[str] = None


@dataclass
class StreamStep:
    """Structured unpacking of the common prefix of a raw stream tuple.

    ``stream_steps`` yields heterogeneous positional tuples. Only ``tool_result``
    carries extra fields at positions 3..5 (parsed separately by
    :func:`parse_tool_result_step`); every other event is fully described by the
    ``event_type`` plus up to four positional values. This decodes that common
    prefix once so consumers stop hand-writing ``step[0..4]`` / ``len(step)``
    index arithmetic.
    """

    event_type: str = ""
    val1: str = ""
    val2: str = ""
    val3: Any = None
    val4: Any = None


@dataclass
class ToolResult:
    """First-class structured result of a tool execution.

    ``content`` is the XML token-efficient string the LLM sees.
    ``display`` is the optional human-friendly renderable text for the UI.
    """

    content: Optional[str] = None
    display: Optional[str] = None
    status: ToolResultStatus = ToolResultStatus.DONE
    returncode: Optional[int] = None
    task_id: Optional[str] = None
    background_task_id: Optional[str] = None
    log_path: Optional[str] = None

    @property
    def is_error(self) -> bool:
        return bool(self.status == ToolResultStatus.ERROR)

    @classmethod
    def done(
        cls,
        content: str = "",
        display: Optional[str] = None,
        returncode: Optional[int] = None,
        task_id: Optional[str] = None,
        background_task_id: Optional[str] = None,
        log_path: Optional[str] = None,
    ) -> "ToolResult":
        c = content or ""
        tid = task_id or background_task_id
        return cls(
            content=c,
            display=display if display is not None else c,
            status=ToolResultStatus.DONE,
            returncode=returncode,
            task_id=tid,
            background_task_id=tid,
            log_path=log_path,
        )

    @classmethod
    def error(
        cls,
        kind: str,
        detail: str = "",
        name: str = "",
        returncode: Optional[int] = None,
        display: Optional[str] = None,
        task_id: Optional[str] = None,
        background_task_id: Optional[str] = None,
        log_path: Optional[str] = None,
    ) -> "ToolResult":
        from johnston.core.domain.defaults.errors import format_tool_error

        formatted = format_tool_error(kind, detail=detail, name=name)
        tid = task_id or background_task_id
        return cls(
            content=formatted,
            display=display if display is not None else formatted,
            status=ToolResultStatus.ERROR,
            returncode=returncode,
            task_id=tid,
            background_task_id=tid,
            log_path=log_path,
        )

    @classmethod
    def cancelled(
        cls,
        content: str = "",
        display: Optional[str] = None,
        task_id: Optional[str] = None,
        background_task_id: Optional[str] = None,
        log_path: Optional[str] = None,
    ) -> "ToolResult":
        c = content or ""
        tid = task_id or background_task_id
        return cls(
            content=c,
            display=display if display is not None else c,
            status=ToolResultStatus.CANCELLED,
            returncode=None,
            task_id=tid,
            background_task_id=tid,
            log_path=log_path,
        )

    def __str__(self) -> str:
        return self.content or ""


async def normalize_tool_result(result: Any) -> ToolResult:
    """Normalize a raw tool-execution result into a :class:`ToolResult`.

    Single shared implementation for every execution path (native tools via
    ``tools.registry``, MCP adapter output, agent-side normalization). Accepts
    one result value or an awaitable. Structured ``ToolResult`` objects pass
    through unchanged; raw ``str``/``None``/dict values are normalized without
    string heuristics. Status is governed strictly via ToolResult.error() or
    explicit returncode != 0.
    """
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, ToolResult):
        return result
    if result is None:
        return ToolResult.done("")
    if isinstance(result, Exception):
        return ToolResult.error("execute", detail=str(result))
    if isinstance(result, (dict, list)):
        return ToolResult.done(json.dumps(result, ensure_ascii=False))
    rc = getattr(result, "returncode", None)
    if rc is not None and rc != 0:
        return ToolResult(content=str(result), status=ToolResultStatus.ERROR, returncode=rc)
    return ToolResult.done(str(result))


__all__ = [
    "StreamStep",
    "ToolResult",
    "ToolResultEvent",
    "ToolResultStatus",
    "normalize_tool_result",
]
