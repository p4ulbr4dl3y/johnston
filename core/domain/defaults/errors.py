"""Pure error-string helpers and the structured tool-result entity for the domain layer. No IO, no state."""
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

__all__ = [
    "ToolResult",
    "ToolResultStatus",
    "ToolResultEvent",
    "FormattedToolError",
    "format_tool_error",
    "parse_tool_result_step",
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

    ``content`` is the string the LLM/UI sees (never raw metadata). Status and
    error text are kept separate; ``is_error`` is derived from ``status`` so the
    two can never drift. ``str(result)`` yields ``content`` (or ``""``) so code
    that expects a string keeps working where that is strategically acceptable,
    but callers should prefer explicit ``-> ToolResult`` annotations.
    """

    content: Optional[str] = None
    status: ToolResultStatus = ToolResultStatus.DONE
    returncode: Optional[int] = None

    @property
    def is_error(self) -> bool:
        return bool(self.status == ToolResultStatus.ERROR)

    @classmethod
    def done(cls, content: str = "", returncode: Optional[int] = None) -> "ToolResult":
        return cls(content=content or "", status=ToolResultStatus.DONE, returncode=returncode)

    @classmethod
    def error(
        cls,
        kind: str,
        detail: str = "",
        name: str = "",
        returncode: Optional[int] = None,
    ) -> "ToolResult":
        return cls(
            content=format_tool_error(kind, detail=detail, name=name),
            status=ToolResultStatus.ERROR,
            returncode=returncode,
        )

    @classmethod
    def cancelled(cls, content: str = "") -> "ToolResult":
        return cls(content=content or "", status=ToolResultStatus.CANCELLED, returncode=None)

    def __str__(self) -> str:
        return self.content or ""
