"""Pure error-string helpers and the structured tool-result entity for the domain layer. No IO, no state."""
import inspect
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Sequence

__all__ = [
    "ToolResult",
    "ToolResultStatus",
    "ToolResultEvent",
    "FormattedToolError",
    "format_tool_error",
    "parse_tool_result_step",
    "normalize_tool_result",
]


class FormattedToolError(ValueError):
    """ValueError whose message is already a fully formatted ``ERR:`` tool-error string.

    Tools raise it for validation/match failures so executors can pass the text
    through verbatim instead of string-sniffing the ``ERR:`` prefix.
    """


class ToolResultStatus(str, Enum):
    """Canonical lifecycle status of a tool execution.

    ``str``-mixed so legacy string comparisons (``status == "error"``) keep
    working and ``.value`` yields the wire/JSON string.
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


def format_tool_error(kind: str, detail: str = "", name: str = "") -> str:
    """Unified error prefix for tool/agent messages.

    Produces `ERR: <kind> '<name>': <detail>` (or `ERR: <kind>` when both name
    and detail are empty). Matches the existing de-facto `ERR:` convention.
    """
    base = f"ERR: {kind}"
    if name:
        base += f" '{name}'"
    if detail:
        base += f": {detail}"
    return base


def parse_tool_result_step(step: Sequence) -> ToolResultEvent:
    """Parse a ``tool_result`` stream tuple into a :class:`ToolResultEvent`.

    The stream yields heterogeneous positional tuples; only ``tool_result``
    carries is_error/status/returncode at positions 3..5. Consumers use this
    shared helper instead of duplicating index arithmetic. Tolerant of the
    short form (``("tool_result", content, "")``) used in tests/fixtures.
    """
    content = step[1] if len(step) > 1 else ""
    is_error = bool(step[3]) if len(step) > 3 else False
    status = step[4] if len(step) > 4 else None
    returncode = step[5] if len(step) > 5 else None
    return ToolResultEvent(
        content=content,
        is_error=is_error,
        status=ToolResultStatus(status) if status is not None else None,
        returncode=returncode,
    )


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

    @property
    def is_error(self) -> bool:
        return bool(self.status == ToolResultStatus.ERROR)

    @classmethod
    def done(cls, content: str = "", display: Optional[str] = None, returncode: Optional[int] = None) -> "ToolResult":
        c = content or ""
        return cls(content=c, display=display if display is not None else c, status=ToolResultStatus.DONE, returncode=returncode)

    @classmethod
    def error(
        cls,
        kind: str,
        detail: str = "",
        name: str = "",
        returncode: Optional[int] = None,
        display: Optional[str] = None,
    ) -> "ToolResult":
        formatted = format_tool_error(kind, detail=detail, name=name)
        return cls(
            content=formatted,
            display=display if display is not None else formatted,
            status=ToolResultStatus.ERROR,
            returncode=returncode,
        )

    @classmethod
    def cancelled(cls, content: str = "", display: Optional[str] = None) -> "ToolResult":
        c = content or ""
        return cls(content=c, display=display if display is not None else c, status=ToolResultStatus.CANCELLED, returncode=None)

    def __str__(self) -> str:
        return self.content or ""


async def normalize_tool_result(result: Any) -> ToolResult:
    """Normalize a raw tool-execution result into a :class:`ToolResult`.

    Single shared implementation for every execution path (native tools via
    ``tools.registry``, MCP adapter output, agent-side normalization). Accepts
    one result value or an awaitable. Structured ``ToolResult`` objects pass
    through unchanged; raw ``str``/``None``/dict values (e.g. MCP adapter
    output) are normalized by inspecting the ``ERR:`` prefix convention, never
    treated as errors otherwise.
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
    text = str(result)
    if text.lstrip().lower().startswith("err:"):
        return ToolResult(content=text, status=ToolResultStatus.ERROR)
    return ToolResult.done(text)
