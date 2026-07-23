import asyncio
import os
import pty
import re
import time
from typing import Any, Dict

from core.background_task import BackgroundTask
from core.bash_guard import analyze_bash_command
from tools.base import BaseTool, truncate_output

SLEEP_CHAIN_REGEX = re.compile(r'^sleep\s+([0-9]+(?:\.[0-9]+)?)\s*(?:(?:&&|;)\s*(.*))?$', re.DOTALL)


class BashTool(BaseTool):
    name = "bash"
    description = "Run terminal command. >10s runs in background."
    schema = {
        "type": "function",
        "function": {
            "name": "bash",
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
        cmd = args.get("command", "").strip()

        # Handle sleep via Python asyncio.sleep without spawning background tasks
        m = SLEEP_CHAIN_REGEX.match(cmd)
        if m:
            sec = float(m.group(1))
            remainder = (m.group(2) or "").strip()
            await asyncio.sleep(sec)
            if not remainder:
                return f"Slept for {sec} seconds."
            cmd = remainder

        skip_confirm = args.get("skip_confirm", False)
        is_safe, reason = analyze_bash_command(cmd)
        if not is_safe and not skip_confirm and ctx.app:
            try:
                from widgets.modal_screens import BashConfirmScreen
                screen = BashConfirmScreen(command=cmd, reason=reason)
                loop = asyncio.get_running_loop()
                future = loop.create_future()

                def on_dismiss(result: Any) -> None:
                    if not future.done():
                        future.set_result(bool(result))

                ctx.app.push_screen(screen, callback=on_dismiss)
                confirmed = await future
                if not confirmed:
                    return "Command execution rejected by user."
            except Exception as e:
                return f"Error prompting for command permission: {e}"

        master_fd = None
        slave_fd = None
        reader = None

        try:
            master_fd, slave_fd = pty.openpty()
        except Exception:
            master_fd, slave_fd = None, None

        env = os.environ.copy()
        env["TERM"] = "dumb"
        env["NO_COLOR"] = "1"
        env["PYTHONUNBUFFERED"] = "1"

        if master_fd is not None and slave_fd is not None:
            try:
                p = await asyncio.create_subprocess_shell(
                    cmd,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    env=env,
                    close_fds=True,
                    start_new_session=True
                )
            finally:
                os.close(slave_fd)

            os.set_blocking(master_fd, False)
            loop = asyncio.get_running_loop()
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            await loop.connect_read_pipe(lambda: protocol, os.fdopen(master_fd, "rb", buffering=0))
        else:
            p = await asyncio.create_subprocess_shell(
                cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env
            )

        task_id = f"bash_{int(time.time())}"
        target_widget = getattr(ctx.app, "current_tool_widget", None) if ctx.app else None
        task = BackgroundTask(task_id, cmd, p, widget=target_widget, master_fd=master_fd, reader=reader)
        task.start_reading(ctx.app, getattr(ctx.app, "on_background_bash_completed", None) if ctx.app else None)

        no_bg = args.get("no_background", False)
        if no_bg:
            await p.wait()
            if hasattr(task, "read_task") and task.read_task:
                try:
                    await asyncio.wait_for(task.read_task, timeout=1.0)
                except asyncio.TimeoutError:
                    pass
            await asyncio.sleep(0.02)
            res = task.get_formatted_output()
            if not res.strip():
                return "Command executed with no output."
            return truncate_output(res, max_chars=4000, hint="Pipe output to grep/head/tail if complete log is needed.")

        try:
            await asyncio.wait_for(p.wait(), timeout=10.0)
            if hasattr(task, "read_task") and task.read_task:
                try:
                    await asyncio.wait_for(task.read_task, timeout=1.0)
                except asyncio.TimeoutError:
                    pass
            await asyncio.sleep(0.02)
            res = task.get_formatted_output()
            if not res.strip():
                return "Command executed with no output."
            return truncate_output(res, max_chars=4000, hint="Pipe output to grep/head/tail if complete log is needed.")
        except asyncio.TimeoutError:
            if ctx.app:
                task.is_background = True
                ctx.add_background_task(task)
                ctx.notify(f"Command sent to background (TID: {task_id})")
                return f"[Background Task ID: {task_id}] Command is running in the background. You will be notified automatically when it finishes. Use manage_task to inspect active background tasks."
            else:
                await p.wait()
                if hasattr(task, "read_task") and task.read_task:
                    try:
                        await asyncio.wait_for(task.read_task, timeout=1.0)
                    except asyncio.TimeoutError:
                        pass
                res = task.get_formatted_output()
                if not res.strip():
                    return "Command executed with no output."
                return truncate_output(res, max_chars=4000, hint="Pipe output to grep/head/tail if complete log is needed.")

