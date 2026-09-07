from typing import Any, Dict

from core.domain.defaults.errors import ToolResult, ToolResultStatus
from core.infrastructure.tasks.manage import (
    filter_to_session,
    find_any,
    not_found_message,
)
from tools.base import BaseTool


class ManageShellTool(BaseTool):
    name = "manage_shell"
    description = "Control active background shell tasks: send stdin input or terminate process."
    schema = {
        "type": "function",
        "function": {
            "name": "manage_shell",
            "description": "Control active background shell tasks: send stdin input or terminate process.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["send_input", "kill"],
                        "description": (
                            "Operation: 'send_input' (send stdin to task), 'kill' (terminate process)."
                        ),
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Background task_id (required).",
                    },
                    "input": {
                        "type": "string",
                        "description": "Input text to write to process stdin (required for 'send_input').",
                    },
                },
                "required": ["action", "task_id"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        args = args or {}
        ctx = self._ensure_context(ctx)
        action = (args.get("action") or "").strip().lower()
        task_id = (args.get("task_id") or "").strip()

        tasks = ctx.background_tasks
        if not tasks and not ctx.host:
            return ToolResult.error("manager", name="none", detail="available")
        curr_sid = ctx.session_id or ""
        tasks = filter_to_session(tasks, curr_sid)

        if not action:
            return ToolResult.error("params", name="action", detail="required ('send_input' or 'kill')")

        if action not in ("send_input", "kill"):
            return ToolResult.error("action", detail="use 'send_input' or 'kill'", name=action)

        if not task_id:
            return ToolResult.error(
                "params",
                name="task_id",
                detail=f"required for '{action}'.",
            )

        if action == "send_input":
            input_text = args.get("input", "") or ""
            t = find_any(tasks, task_id)
            if t is None:
                return ToolResult(content=not_found_message(task_id, tasks, "background"), display="", status=ToolResultStatus.ERROR)
            if not getattr(t, "is_active", getattr(t, "is_running", False)):
                return ToolResult.error("notrunning", name=task_id)
            if hasattr(t, "send_input"):
                res = await t.send_input(input_text)
                return ToolResult.done(content=res, display="")
            return ToolResult.error("nowrite", name=task_id, detail="stdin not writable")

        elif action == "kill":
            t = find_any(tasks, task_id)
            if t is None:
                if ctx.host and hasattr(ctx.host, "_background_shell_widgets") and isinstance(ctx.host._background_shell_widgets, dict):
                    ctx.host._background_shell_widgets.pop(task_id, None)
                return ToolResult(content=not_found_message(task_id, tasks, "background"), display="", status=ToolResultStatus.ERROR)
            if getattr(t, "is_active", getattr(t, "is_running", False)):
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
                finally:
                    if ctx.host and hasattr(ctx.host, "_background_shell_widgets") and isinstance(ctx.host._background_shell_widgets, dict):
                        widget = ctx.host._background_shell_widgets.pop(task_id, None)
                        if widget is not None and hasattr(widget, "set_result"):
                            try:
                                widget.set_result(t.get_formatted_output() if hasattr(t, "get_formatted_output") else "[killed]", status="done")
                            except Exception:
                                pass
            if ctx.host and hasattr(ctx.host, "_background_shell_widgets") and isinstance(ctx.host._background_shell_widgets, dict):
                ctx.host._background_shell_widgets.pop(task_id, None)
            return ToolResult.error("notrunning", name=task_id)

        return ToolResult.error("action", detail="use 'send_input' or 'kill'", name=action)
