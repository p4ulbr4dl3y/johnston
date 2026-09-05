import re

from core.infrastructure.tasks.output import is_spinner_line, process_carriage_returns
from widgets.presentation.tool_renderers import format_truncation_for_ui

_TRUNC_BANNER_START = re.compile(r"(?:\.\.\.\s*)?\[(?:Output\s+truncated|Truncated)", re.IGNORECASE)


def bash_safe_boundary(examine: str) -> int:
    """Byte offset in ``examine`` up to which the flush can commit safely."""
    boundary = examine.rfind("\n") + 1
    committed = examine[:boundary]
    last_close = committed.rfind("]")
    for m in _TRUNC_BANNER_START.finditer(committed):
        if m.start() > last_close:
            boundary = examine.rfind("\n", 0, m.start()) + 1
            break
    return boundary


def bash_ends_with_spinner(text: str) -> bool:
    """True when the last line of ``text`` is a single spinner character."""
    if not text:
        return False
    return is_spinner_line(text.rsplit("\n", 1)[-1])


def compose_bash_result(
    tail: str,
    carry_raw: str,
    tail_line_is_spinner: bool,
    leading_stripped: bool,
) -> str:
    """Reconstruct ``result_text`` from the committed tail + carried remainder."""
    if carry_raw:
        part = process_carriage_returns(
            format_truncation_for_ui(carry_raw, strip_edges=False).rstrip()
        )
        if (
            tail
            and tail_line_is_spinner
            and "\n" not in part
            and is_spinner_line(part)
        ):
            nl = tail.rfind("\n")
            tail = (tail[: nl + 1] if nl != -1 else "") + part
        else:
            tail = f"{tail}\n{part}" if tail else part
    if leading_stripped:
        return tail.rstrip()
    return tail.strip()
