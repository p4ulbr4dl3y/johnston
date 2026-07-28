from typing import Any, Dict

from tools.base import BaseTool


class ManageTaskTool(BaseTool):
    name = "manage_task"
    description = "Manage background CLI commands spawned via shell. Actions: 'list' (list running commands), 'status' (get output log for task; do not poll running tasks in a loop), 'kill' (terminate task), 'send_input' (send stdin input to running task)."
    schema = {
        "type": "function",
        "function": {
            "name": "manage_task",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "status", "kill", "send_input"], "description": "Action: 'list', 'status', 'kill', or 'send_input'"},
                    "task_id": {"type": "string", "description": "Target background task ID"},
                    "input": {"type": "string", "description": "Input text to send (required for 'send_input')"}
                },
                "required": ["action"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        ctx = self._ensure_context(app)
        action = args.get("action", "list").lower()
        task_id = args.get("task_id", "").strip()

        tasks = ctx.background_tasks
        if not tasks and not ctx.app:
            return "No background task manager available."

        if action == "list":
            if not tasks:
                return "No background tasks currently active."
            lines = ["Active Background Tasks:"]
            for t in tasks:
                status = "RUNNING" if t.is_running else "FINISHED"
                lines.append(f"- ID: {t.task_id} | Status: {status} | Command: {t.command}")
            return "\n".join(lines)

        elif action == "status":
            if not task_id:
                return "Error: task_id parameter required for 'status' action."
            matching = [t for t in tasks if t.task_id == task_id]
            if not matching:
                return f"No task found with ID: {task_id}. Do NOT poll in a loop. Use manage_task(action='list') to see active tasks, or end your turn."
            t = matching[0]
            out = "".join(t.output)
            if len(out) > 4000:
                out = out[-4000:] + "\n... [truncated]"
            if t.is_running:
                return f"Task ID: {t.task_id}\nStatus: RUNNING\nCommand: {t.command}\n\nRecent Output:\n{out or '(No output yet)'}\n\nNote: Task is still running. STOP calling manage_task(status) in a loop and end your turn now."
            return f"Task ID: {t.task_id}\nStatus: FINISHED\nCommand: {t.command}\n\nRecent Output:\n{out or '(No output yet)'}"

        elif action in ("send_input", "input"):
            if not task_id:
                return "Error: task_id parameter required for 'send_input' action."
            input_text = args.get("input", "")
            if input_text is None:
                input_text = ""
            matching = [t for t in tasks if t.task_id == task_id]
            if not matching:
                return f"No task found with ID: {task_id}"
            t = matching[0]
            if not getattr(t, "is_running", False):
                return f"Task {task_id} is not running."

            if hasattr(t, "send_input"):
                return await t.send_input(input_text)
            return f"Task {task_id} does not support stdin input."

        elif action == "kill":
            if not task_id:
                return "Error: task_id parameter required for 'kill' action."
            matching = [t for t in tasks if t.task_id == task_id]
            if not matching:
                return f"No task found with ID: {task_id}"
            t = matching[0]
            if getattr(t, "is_running", False):
                try:
                    if hasattr(t, "kill"):
                        await t.kill()
                    elif getattr(t, "process", None) and t.process.returncode is None:
                        t.process.kill()
                    t.is_running = False
                    ctx.refresh_status()
                    return f"Task {task_id} successfully killed."
                except Exception as e:
                    return f"Failed to kill task {task_id}: {e}"
            return f"Task {task_id} is not running."

        return f"Unknown action: {action}. Use 'list', 'status', 'kill', or 'send_input'."
