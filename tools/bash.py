import asyncio
import time
from typing import Any, Dict
from tools.base import BaseTool
from core.background_task import BackgroundTask

class BashTool(BaseTool):
    name = "Bash"
    description = "Run terminal command. >5s runs in background."

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
            if len(res) > 3000:
                res = res[:3000] + "\n... [output truncated]"
            return res if res.strip() else "Command executed with no output."
        except asyncio.TimeoutError:
            if ctx.app:
                task.is_background = True
                ctx.add_background_task(task)
                ctx.notify(f"Command sent to background (TID: {task_id})")
                return f"[Background Task ID: {task_id}] Bash command is running in the background. I must wait for its completion. Do not run any other tools until notified. (посмотреть таски - /tasks в панеле чата)"
            else:
                await p.wait()
                if hasattr(task, "read_task") and task.read_task:
                    await task.read_task
                res = "".join(task.output)
                if len(res) > 3000:
                    res = res[:3000] + "\n... [output truncated]"
                return res if res.strip() else "Command executed with no output."
