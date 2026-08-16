"""Pure error-string helpers and the structured tool-result entity for the domain layer. No IO, no state."""
from dataclasses import dataclass
from typing import Optional

__all__ = ["ToolResult", "format_tool_error"]


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


@dataclass
class ToolResult:
    """First-class structured result of a tool execution.

    ``content`` is the string the LLM/UI sees (never raw metadata). Status and
    error text are kept separate; the factories guarantee ``is_error`` and
    ``status`` stay in sync. ``str(result)`` yields ``content`` (or ``""``) so
    code that expects a string keeps working where that is strategically
    acceptable, but callers should prefer explicit ``-> ToolResult`` annotations.
    """

    content: Optional[str] = None
    is_error: bool = False
    status: str = "done"  # "done" | "error" | "running" | "cancelled"
    returncode: Optional[int] = None

    @classmethod
    def done(cls, content: str = "", returncode: Optional[int] = None) -> "ToolResult":
        return cls(content=content or "", is_error=False, status="done", returncode=returncode)

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
            is_error=True,
            status="error",
            returncode=returncode,
        )

    @classmethod
    def cancelled(cls, content: str = "") -> "ToolResult":
        return cls(content=content or "", is_error=False, status="cancelled", returncode=None)

    def __str__(self) -> str:
        return self.content or ""
