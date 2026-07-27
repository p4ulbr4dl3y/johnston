import asyncio
import itertools
import os
import re
import time
from typing import Any, Dict

from core.background_task import BackgroundTask
from core.bash_guard import analyze_shell_command
from core.platform_utils import (
    is_windows,
    shell_env,
    shell_executable,
    shell_subprocess_kwargs,
    supports_pty,
)
from tools.base import BaseTool, truncate_output

SLEEP_CHAIN_REGEX = re.compile(r'^sleep\s+([0-9]+(?:\.[0-9]+)?)\s*(?:(?:&&|;)\s*(.*))?$', re.DOTALL)
_TASK_ID_COUNTER = itertools.count()


def _new_task_id() -> str:
    return f"shell_{time.time_ns()}_{next(_TASK_ID_COUNTER)}"


class ShellTool(BaseTool):
    name = "shell"
    description = "Run a terminal command. Commands running longer than 60 seconds are automatically moved to the background; use manage_task to inspect, send input, or kill them. Destructive commands require user confirmation."

    schema = {
        "type": "function",
        "function": {
            "name": "shell",
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Terminal command to run"},
                    "no_background": {
                        "type": "boolean",
                        "description": "If true, block until the command finishes instead of moving long-running commands to the background.",
                    },
                },
                "required": ["command"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        ctx = self._ensure_context(app)
        cmd = args.get("command", "").strip()

        m = SLEEP_CHAIN_REGEX.match(cmd)
        if m:
            sec = float(m.group(1))
            remainder = (m.group(2) or "").strip()
            await asyncio.sleep(sec)
            if not remainder:
                return f"Slept for {sec} seconds."
            cmd = remainder

        skip_confirm = args.get("skip_confirm", False)
        is_safe, reason = analyze_shell_command(cmd)
        if not is_safe and not skip_confirm and ctx.app:
            try:
                from widgets.modal_screens import BashConfirmScreen

                screen = BashConfirmScreen(command=cmd, reason=reason)
                loop = asyncio.get_running_loop()
                future = loop.create_future()

                def on_dismiss(result: bool) -> None:
                    if not future.done():
                        future.set_result(bool(result))

                ctx.app.push_screen(screen, callback=on_dismiss)
                confirmed = await future
                if not confirmed:
                    return "Command execution rejected by user."
            except Exception as e:
                return f"Error prompting for command permission: {e}"

        env = shell_env()
        master_fd = None
        slave_fd = None
        reader = None
        transport = None
        use_pty = False

        if supports_pty():
            try:
                import pty

                master_fd, slave_fd = pty.openpty()
                os.set_blocking(master_fd, False)
                loop = asyncio.get_running_loop()
                reader = asyncio.StreamReader()
                protocol = asyncio.StreamReaderProtocol(reader)
                transport, _ = await loop.connect_read_pipe(
                    lambda: protocol, os.fdopen(master_fd, "rb", buffering=0)
                )
                use_pty = True
            except Exception:
                for fd in (master_fd, slave_fd):
                    if fd is not None:
                        try:
                            os.close(fd)
                        except Exception:
                            pass
                master_fd = None
                slave_fd = None
                reader = None
                transport = None

        if is_windows():
            p = await self._create_windows_process(cmd, env)
        elif use_pty:
            try:
                p = await asyncio.create_subprocess_shell(
                    cmd,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    env=env,
                    close_fds=True,
                )
            finally:
                if slave_fd is not None:
                    try:
                        os.close(slave_fd)
                    except Exception:
                        pass
        else:
            p = await asyncio.create_subprocess_shell(
                cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                executable=shell_executable(),
                **shell_subprocess_kwargs(),
            )

        task_id = _new_task_id()
        target_widget = getattr(ctx.app, "current_tool_widget", None) if ctx.app else None
        task = BackgroundTask(
            task_id,
            cmd,
            p,
            widget=target_widget,
            master_fd=master_fd,
            reader=reader,
            transport=transport,
        )
        callback = None
        if ctx.app:
            callback = getattr(ctx.app, "on_background_shell_completed", None) or getattr(
                ctx.app, "on_background_bash_completed", None
            )
        task.start_reading(ctx.app, callback)

        no_bg = args.get("no_background", False)
        if no_bg:
            await p.wait()
            if task.read_task:
                try:
                    await asyncio.wait_for(task.read_task, timeout=1.0)
                except asyncio.TimeoutError:
                    pass
            task.close_pty()
            await asyncio.sleep(0.02)
            res = task.get_formatted_output()
            if not res.strip():
                return "Command executed with no output."
            return truncate_output(res, max_chars=4000, hint="Pipe output to grep/head/tail if complete log is needed.")

        try:
            await asyncio.wait_for(p.wait(), timeout=60.0)
            if task.read_task:
                try:
                    await asyncio.wait_for(task.read_task, timeout=2.0)
                except asyncio.TimeoutError:
                    pass
            task.close_pty()
            res = task.get_formatted_output()
            if not res.strip():
                return "Command executed with no output."
            return truncate_output(res, max_chars=4000, hint="Pipe output to grep/head/tail if complete log is needed.")
        except asyncio.TimeoutError:
            task.is_background = True
            ctx.add_background_task(task)
            if ctx.app:
                ctx.notify(f"Command sent to background (TID: {task_id})")
            return f"[Background Task ID: {task_id}] Command is running in the background. You will be notified automatically when it finishes."

    async def _create_windows_process(self, command: str, env: dict[str, str]):
        shell = shell_executable()
        if shell and shell.lower().endswith(("pwsh.exe", "pwsh", "powershell.exe", "powershell")):
            return await asyncio.create_subprocess_exec(
                shell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                **shell_subprocess_kwargs(),
            )
        if shell and shell.lower().endswith(("cmd.exe", "cmd")):
            return await asyncio.create_subprocess_exec(
                shell,
                "/d",
                "/s",
                "/c",
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                **shell_subprocess_kwargs(),
            )
        return await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            **shell_subprocess_kwargs(),
        )
