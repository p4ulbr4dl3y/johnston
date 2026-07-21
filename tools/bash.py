import asyncio
import time
from typing import Any, Dict

from core.background_task import BackgroundTask
from tools.base import BaseTool, truncate_output


class BashTool(BaseTool):
    name = "Bash"
    description = "Run terminal command. >5s runs in background."
    schema = {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "Run terminal command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Terminal command"}
                },
                "required": ["command"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        ctx = self._ensure_context(app)
        cmd = args.get("command", "")
        p = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        task_id = f"bash_{int(time.time())}"
        task = BackgroundTask(task_id, cmd, p)
        task.start_reading(ctx.app, getattr(ctx.app, "on_background_bash_completed", None) if ctx.app else None)

        try:
            await asyncio.wait_for(p.wait(), timeout=5.0)
            if hasattr(task, "read_task") and task.read_task:
                await task.read_task
            res = "".join(task.output)
            if not res.strip():
                return "Command executed with no output."
            return truncate_output(res, max_chars=4000, hint="Pipe output to grep/head/tail if complete log is needed.")
        except asyncio.TimeoutError:
            if ctx.app:
                task.is_background = True
                ctx.add_background_task(task)
                ctx.notify(f"Command sent to background (TID: {task_id})")
                return f"[Background Task ID: {task_id}] Command is running in the background. You will be notified automatically when it finishes. Use ManageTask to inspect active background tasks."
            else:
                await p.wait()
                if hasattr(task, "read_task") and task.read_task:
                    await task.read_task
                res = "".join(task.output)
                if not res.strip():
                    return "Command executed with no output."
                return truncate_output(res, max_chars=4000, hint="Pipe output to grep/head/tail if complete log is needed.")
