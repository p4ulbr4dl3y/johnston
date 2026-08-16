from typing import Any, Dict

from core.infrastructure.errors import format_tool_error
from core.infrastructure.tasks.manage import filter_to_session, find_any, list_lines, not_found_message
from tools.base import BaseTool


class ManageShellTool(BaseTool):
    name = "manage_shell"
    description = "Interact with active background processes (send stdin or kill)."
    schema = {
        "type": "function",
        "function": {
            "name": "manage_shell",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "send_input", "kill"]},
                    "task_id": {"type": "string", "description": "Background task ID"},
                    "input": {"type": "string", "description": "Input text for send_input"},
                },
                "required": ["action"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> str:
        from tools.registry import normalize_tool_args

        args = normalize_tool_args("manage_shell", args)
        ctx = self._ensure_context(ctx)
        action = args.get("action", "list").lower()
        task_id = (args.get("task_id") or "").strip()

        tasks = ctx.background_tasks
        if not tasks and not ctx.app:
            return format_tool_error("manager", name="none", detail="available")

        # Scope to the current session, matching the tasks screen and status footer.
        curr_sid = ctx.session_id
        tasks = filter_to_session(tasks, curr_sid)

        if action == "list":
            return list_lines(tasks)

        elif action in ("send_input", "input"):
            if not task_id:
                return format_tool_error("params", name="task_id", detail="required for 'send_input'")
            input_text = args.get("input", "") or ""
            t = find_any(tasks, task_id)
            if t is None:
                return not_found_message(task_id, tasks, "background")
            if not getattr(t, "is_running", False):
                return format_tool_error("notrunning", name=task_id)

            if hasattr(t, "send_input"):
                return await t.send_input(input_text)
            return format_tool_error("nowrite", name=task_id, detail="stdin not writable")

        elif action == "kill":
            if not task_id:
                return format_tool_error("params", name="task_id", detail="required for 'kill'")
            t = find_any(tasks, task_id)
            if t is None:
                return not_found_message(task_id, tasks, "background")
            if getattr(t, "is_running", False):
                try:
                    if hasattr(t, "kill"):
                        await t.kill()
                    elif getattr(t, "process", None) and t.process.returncode is None:
                        t.process.kill()
                    ctx.refresh_status()
                    return f"{task_id} killed"
                except Exception as e:
                    return format_tool_error("kill", detail=str(e), name=task_id)
            return format_tool_error("notrunning", name=task_id)

        return format_tool_error("action", detail="use 'list', 'send_input', or 'kill'", name=action)
