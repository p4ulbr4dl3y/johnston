from typing import Any, Dict

from core.domain.defaults.errors import ToolResult
from core.infrastructure.tasks.manage import filter_to_session, find_any, list_lines, not_found_message
from tools.base import BaseTool


class ManageShellTool(BaseTool):
    name = "manage_shell"
    description = "Manage background shell processes: list running tasks, send stdin input, or kill."
    schema = {
        "type": "function",
        "function": {
            "name": "manage_shell",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "send_input", "kill"],
                        "description": "Action to perform",
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

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        args = args or {}
        ctx = self._ensure_context(ctx)
        action = args.get("action", "list").lower()
        task_id = (args.get("task_id") or "").strip()

        tasks = ctx.background_tasks
        if not tasks and not ctx.host:
            return ToolResult.error("manager", name="none", detail="available")
        curr_sid = ctx.session_id
        tasks = filter_to_session(tasks, curr_sid)

        if action == "list":
            return ToolResult.done(list_lines(tasks))

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
                return ToolResult.done(not_found_message(task_id, tasks, "background"))
            if not getattr(t, "is_running", False):
                return ToolResult.error("notrunning", name=task_id)
            if hasattr(t, "send_input"):
                return ToolResult.done(await t.send_input(input_text))
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
                return ToolResult.done(not_found_message(task_id, tasks, "background"))
            if getattr(t, "is_running", False):
                try:
                    if hasattr(t, "kill"):
                        await t.kill()
                    elif getattr(t, "process", None) and t.process.returncode is None:
                        t.process.kill()
                    ctx.refresh_status()
                    return ToolResult.done(f"{task_id} killed")
                except Exception as e:
                    return ToolResult.error("kill", detail=str(e), name=task_id)
            return ToolResult.error("notrunning", name=task_id)

        return ToolResult.error("action", detail="use 'list', 'send_input', or 'kill'", name=action)
