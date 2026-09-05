from typing import Any, Dict

from core.domain.defaults.errors import ToolResult, ToolResultStatus
from core.infrastructure.tasks.manage import (
    filter_to_session,
    find_any,
    format_tasks_plain,
    not_found_message,
)
from tools.base import BaseTool


class ManageShellTool(BaseTool):
    name = "manage_shell"
    description = "Control active background shell tasks."
    schema = {
        "type": "function",
        "function": {
            "name": "manage_shell",
            "description": "Control active background shell tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "send_input", "kill"],
                        "description": (
                            "Operation: 'list' (show running tasks), 'send_input' (send stdin to task), 'kill' (terminate process)."
                        ),
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Background task_id (required for 'send_input' and 'kill')",
                    },
                    "input": {
                        "type": "string",
                        "description": "Input text to write to process stdin (required for 'send_input')",
                    },
                },
                "required": ["action"],
            },
        },
    }

    def __init__(self) -> None:
        super().__init__()
        self._breaker_state: Dict[str, tuple[Any, int]] = {}
        self._last_list_fp = None
        self._consecutive_list_count = 0

    def reset_circuit_breaker(self, session_id: str | None = None) -> None:
        """Reset consecutive polling circuit breaker for session or globally."""
        if not hasattr(self, "_breaker_state"):
            self._breaker_state = {}
        if session_id:
            self._breaker_state.pop(session_id, None)
        else:
            self._breaker_state.clear()
        self._last_list_fp = None
        self._consecutive_list_count = 0

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        args = args or {}
        ctx = self._ensure_context(ctx)
        action = (args.get("action") or "list").lower()
        task_id = (args.get("task_id") or "").strip()

        tasks = ctx.background_tasks
        if not tasks and not ctx.host:
            return ToolResult.error("manager", name="none", detail="available")
        curr_sid = ctx.session_id or ""
        tasks = filter_to_session(tasks, curr_sid)

        if not hasattr(self, "_breaker_state"):
            self._breaker_state = {}

        if action == "list":
            fp = [(getattr(t, "id", None), getattr(t, "is_running", None)) for t in (tasks or [])]
            last_fp, count = self._breaker_state.get(curr_sid, (None, 0))
            if last_fp == fp and count >= 1:
                return ToolResult.error(
                    "execute",
                    detail=(
                        "Consecutive polling of 'list' is blocked. Task status has not changed. "
                        "The system automatically wakes you with <notification type='shell'> on exit. "
                        "Stop calling tools to wait."
                    ),
                    name="manage_shell",
                )
            new_count = count + 1 if last_fp == fp else 1
            self._breaker_state[curr_sid] = (fp, new_count)
            self._last_list_fp = fp
            self._consecutive_list_count = new_count

            content_plain = format_tasks_plain(tasks)
            return ToolResult.done(content=content_plain, display="")

        self._breaker_state[curr_sid] = (None, 0)
        self._consecutive_list_count = 0

        if action == "send_input":
            if not task_id:
                return ToolResult.error(
                    "params",
                    name="task_id",
                    detail="required for 'send_input'. Run manage_shell(action='list') to get active task IDs.",
                )
            input_text = args.get("input", "") or ""
            t = find_any(tasks, task_id)
            if t is None:
                return ToolResult(content=not_found_message(task_id, tasks, "background"), display="", status=ToolResultStatus.ERROR)
            if not getattr(t, "is_running", False):
                return ToolResult.error("notrunning", name=task_id)
            if hasattr(t, "send_input"):
                res = await t.send_input(input_text)
                return ToolResult.done(content=res, display="")
            return ToolResult.error("nowrite", name=task_id, detail="stdin not writable")

        elif action == "kill":
            if not task_id:
                return ToolResult.error(
                    "params",
                    name="task_id",
                    detail="required for 'kill'. Run manage_shell(action='list') to get active task IDs.",
                )
            t = find_any(tasks, task_id)
            if t is None:
                return ToolResult(content=not_found_message(task_id, tasks, "background"), display="", status=ToolResultStatus.ERROR)
            if getattr(t, "is_running", False):
                try:
                    setattr(t, "suppress_notification", True)
                    if hasattr(t, "kill"):
                        await t.kill()
                    elif getattr(t, "process", None) and t.process.returncode is None:
                        t.process.kill()
                    ctx.refresh_status()
                    msg = f"[killed {task_id}]"
                    return ToolResult.done(content=msg, display="")
                except Exception as e:
                    return ToolResult.error("kill", detail=str(e), name=task_id)
            return ToolResult.error("notrunning", name=task_id)

        return ToolResult.error("action", detail="use 'list', 'send_input', or 'kill'", name=action)
