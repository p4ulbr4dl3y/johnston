from typing import Any, Dict

from tools.base import BaseTool


class ManageTaskTool(BaseTool):
    name = "ManageTask"
    description = "Manage background tasks. Actions: 'list' (list running tasks), 'status' (get task status and recent output log), 'kill' (cancel/terminate background task)."

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
                return f"No task found with ID: {task_id}"
            t = matching[0]
            status = "RUNNING" if t.is_running else "FINISHED"
            out = "".join(t.output)
            if len(out) > 4000:
                out = out[-4000:] + "\n... [truncated]"
            return f"Task ID: {t.task_id}\nStatus: {status}\nCommand: {t.command}\n\nRecent Output:\n{out or '(No output yet)'}"

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

        return f"Unknown action: {action}. Use 'list', 'status', or 'kill'."
