"""Pure error-string helpers and the structured tool-result entity for the domain layer. No IO, no state."""
from typing import Optional, Sequence

from johnston.core.domain.entities.tool_result import (
    StreamStep,
    ToolResult,
    ToolResultEvent,
    ToolResultStatus,
    normalize_tool_result,
)

__all__ = [
    "FormattedToolError",
    "StreamStep",
    "ToolResult",
    "ToolResultEvent",
    "ToolResultStatus",
    "format_tool_error",
    "normalize_tool_result",
    "parse_stream_step",
    "parse_tool_result_step",
]


class FormattedToolError(ValueError):
    """ValueError whose message is already a fully formatted ``ERR:`` tool-error string.

    Tools raise it for validation/match failures so executors can pass the text
    through verbatim instead of string-sniffing the ``ERR:`` prefix.
    """


def format_tool_error(kind: str, detail: str = "", name: str = "") -> str:
    """Unified error prefix for tool/agent messages.

    Produces `ERR: <kind> '<name>': <detail>` (or `ERR: <kind>` when both name
    and detail are empty). Matches the existing de-facto `ERR:` convention.

    The ``name`` and ``detail`` are XML-escaped so a file path like
    ``/tmp/<system_note kind="interrupted">...</system_note>/img.png``
    cannot inject a synthetic system-note message into the model's view.
    Without escaping, the model could pattern-match on literal
    ``<system_note>`` tags in tool result text and treat the
    injection as authoritative (e.g. skip tool calls per the
    "interrupted" kind). The kind is a closed enum and is safe to render raw.
    """
    from johnston.core.infrastructure.runtime.xml_utils import escape_xml_attr

    base = f"ERR: {kind}"
    if name:
        base += f" '{escape_xml_attr(name)}'"
    if detail:
        base += f": {escape_xml_attr(detail)}"
    return base


def parse_stream_step(step: Sequence) -> Optional[StreamStep]:
    """Parse a raw stream tuple into a :class:`StreamStep`.

    Returns ``None`` for an empty/falsy step so callers can short-circuit
    instead of checking ``if not step`` themselves. Tolerant of short tuples:
    missing positions fall back to ``""`` (val1/val2) or ``None`` (val3/val4).
    """
    if not step:
        return None
    return StreamStep(
        event_type=step[0],
        val1=step[1] if len(step) > 1 else "",
        val2=step[2] if len(step) > 2 else "",
        val3=step[3] if len(step) > 3 else None,
        val4=step[4] if len(step) > 4 else None,
    )


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
    task_id = step[7] if len(step) > 7 else None
    log_path = step[8] if len(step) > 8 else None
    return ToolResultEvent(
        content=content,
        is_error=is_error,
        status=ToolResultStatus(status) if status is not None else None,
        returncode=returncode,
        task_id=task_id,
        background_task_id=task_id,
        log_path=log_path,
    )
