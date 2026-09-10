"""Core shell command execution — NO Textual imports.

Absorbs business logic from the TUI message_flow_shell mixin:
tool execution, session event recording, agent history update.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from johnston.core.domain.entities.tool_result import ToolResult

logger = logging.getLogger(__name__)


@dataclass
class ShellExecResult:
    """Structured result of a shell command execution."""

    content: str
    returncode: int | None
    is_error: bool
    status: str  # "done" or "error"


def _parse_tool_result(res: ToolResult) -> ShellExecResult:
    """Convert a core ToolResult into a ShellExecResult.

    Status resolution mirrors the original TUI mixin: prefer the ToolResult
    status enum value; fall back to ``"error"``/``"done"`` derived from is_error.
    """
    content = res.content or ""
    returncode = res.returncode
    is_error = res.is_error or (returncode is not None and returncode != 0)

    status_value = getattr(res.status, "value", None)
    if isinstance(status_value, str):
        status = status_value
    elif isinstance(res.status, str):
        status = res.status
    else:
        status = "error" if is_error else "done"

    return ShellExecResult(
        content=content,
        returncode=returncode,
        is_error=is_error,
        status=status,
    )


async def execute_shell_command(
    cmd: str,
    *,
    host: Any | None = None,
    session: Any | None = None,
    agent: Any | None = None,
) -> ShellExecResult:
    """Execute a shell command via ShellTool and optionally record to session/agent.

    Parameters
    ----------
    cmd:
        The shell command string to execute.
    host:
        Optional host object for ToolContext (UI app, subagent, etc.).
        Pass ``None`` for headless core usage.
    session:
        Optional session to record the tool event to.
    agent:
        Optional agent whose ``history`` list will receive the entry.
    """
    from johnston.core.tools.context import ToolContext
    from johnston.core.tools.shell import ShellTool

    ctx = ToolContext(app=host)
    tool = ShellTool()

    try:
        res = await tool.execute({"command": cmd}, ctx=ctx)
        result = _parse_tool_result(res)
    except Exception as exc:
        logger.exception("Shell execution failed: %s", exc)
        result = ShellExecResult(
            content=f"ERR: {exc}",
            returncode=1,
            is_error=True,
            status="error",
        )

    if session is not None and hasattr(session, "add_event"):
        session.add_event({
            "type": "tool",
            "tool_type": "shell",
            "target": cmd,
            "result_text": result.content,
            "args": {"command": cmd},
            "status": result.status,
            "returncode": result.returncode,
        })

    if agent is not None and hasattr(agent, "history") and isinstance(agent.history, list):
        history_text = f"! {cmd}\n\n{result.content}".rstrip() if result.content else f"! {cmd}"
        agent.history.append({"role": "user", "content": history_text})

    return result


async def record_shell_to_session(
    session: Any,
    cmd: str,
    result: ShellExecResult,
    *,
    agent: Any | None = None,
) -> None:
    """Record an already-completed shell result to session and optionally agent history.

    Separated from ``execute_shell_command`` so callers that own their own
    execution flow (e.g. background tasks) can record after the fact.
    """
    if session is not None and hasattr(session, "add_event"):
        session.add_event({
            "type": "tool",
            "tool_type": "shell",
            "target": cmd,
            "result_text": result.content,
            "args": {"command": cmd},
            "status": result.status,
            "returncode": result.returncode,
        })

    if agent is not None and hasattr(agent, "history") and isinstance(agent.history, list):
        history_text = f"! {cmd}\n\n{result.content}".rstrip() if result.content else f"! {cmd}"
        agent.history.append({"role": "user", "content": history_text})


__all__ = [
    "ShellExecResult",
    "execute_shell_command",
    "record_shell_to_session",
]
