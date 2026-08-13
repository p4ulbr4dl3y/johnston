from typing import Any, Dict

from core.tasks.manage import filter_to_session, find_any, list_lines, not_found_message
from tools.base import BaseTool, format_tool_error, tail_output


class ManageShellTool(BaseTool):
    name = "manage_shell"
    description = "Manage background shell processes: list, status, kill, send_input."
    schema = {
        "type": "function",
        "function": {
            "name": "manage_shell",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "status", "kill", "send_input"]},
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
        curr_sid = getattr(ctx.app, "current_session_id", None) if ctx.app else None
        tasks = filter_to_session(tasks, curr_sid)

        if action == "list":
            return list_lines(tasks)

        elif action == "status":
            if not task_id:
                return format_tool_error("params", name="task_id", detail="required for 'status'")
            t = find_any(tasks, task_id)
            if t is None:
                return not_found_message(task_id, tasks, "background")
            out = t.get_formatted_output() if hasattr(t, "get_formatted_output") else "".join(t.output)
            out = tail_output(out, 4000)
            if t.is_running:
                return (
                    f"Task ID: {t.task_id}\nStatus: RUNNING\nCommand: {t.command}\n\nRecent Output:\n{out or '(No output yet)'}\n\n"
                    "Note: If Recent Output shows an interactive prompt (e.g., asking for input, confirmation [y/N], or 'Press RETURN'), "
                    f"you may call manage_shell(action='send_input', task_id='{t.task_id}', input='...') to answer it, or manage_shell(action='kill', task_id='{t.task_id}') to abort. "
                    "Otherwise, STOP calling manage_shell(status) in a loop and end your turn now."
                )
            return f"{t.task_id} FINISHED\nCommand: {t.command}\n\nRecent Output:\n{out or '(No output yet)'}"

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
                    t.is_running = False
                    ctx.refresh_status()
                    return f"{task_id} killed"
                except Exception as e:
                    return format_tool_error("kill", detail=str(e), name=task_id)
            return format_tool_error("notrunning", name=task_id)

        return format_tool_error("action", detail="use 'list', 'status', 'kill', or 'send_input'", name=action)
