import asyncio
import itertools
import re
import time
from typing import Any, Dict

from core.background_task import BackgroundTask, process_carriage_returns, strip_ansi
from core.platform_utils import (
    is_windows,
    shell_env,
    shell_executable,
    shell_subprocess_kwargs,
    terminate_process,
)
from tools.base import BaseTool, truncate_output

SLEEP_CHAIN_REGEX = re.compile(r'^sleep\s+([0-9]+(?:\.[0-9]+)?)\s*(?:(?:&&|;)\s*(.*))?$', re.DOTALL)
_TASK_ID_COUNTER = itertools.count(1)


def _new_task_id() -> str:
    return f"shell_{time.time_ns()}_{next(_TASK_ID_COUNTER)}"


class ShellTool(BaseTool):
    name = "shell"
    description = "Run a terminal command. Commands running longer than timeout (default 120s) are automatically moved to the background. Destructive commands require user confirmation."

    schema = {
        "type": "function",
        "function": {
            "name": "shell",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Terminal command to run"},
                    "timeout": {"type": "integer", "description": "Optional timeout in seconds (default: 120, max: 600)"},
                    "run_in_background": {"type": "boolean", "description": "Set to true to run this command in the background immediately."},
                },
                "required": ["command"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        ctx = self._ensure_context(app)
        cmd = args.get("command", "").strip()

        raw_timeout = args.get("timeout", 120)
        try:
            timeout = max(1, min(int(raw_timeout), 600))
        except (ValueError, TypeError):
            timeout = 120

        m = SLEEP_CHAIN_REGEX.match(cmd)
        if m:
            sec = float(m.group(1))
            remainder = (m.group(2) or "").strip()
            if sec > timeout:
                return f"Error: sleep duration ({sec}s) exceeds timeout ({timeout}s)."
            await asyncio.sleep(sec)
            if not remainder:
                return f"Slept for {sec} seconds."
            cmd = remainder

        skip_confirm = bool(args.get("skip_confirm", False))
        from core.shell_guard import analyze_shell_command
        is_safe, reason = analyze_shell_command(cmd)

        if not is_safe and not skip_confirm and ctx.app:
            try:
                from widgets.modal_screens import ShellConfirmScreen

                screen = ShellConfirmScreen(command=cmd, reason=reason)
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
        p = await self._create_std_process(cmd, env)

        run_in_bg = bool(args.get("run_in_background", False))

        # Synchronous execution mode for subagents (no background task)
        if ctx.is_subagent:
            if run_in_bg:
                await terminate_process(p)
                return "Error: Background tasks are not supported in subagents."

            output_chunks = []

            async def _read_stream(stream):
                if not stream:
                    return
                while True:
                    try:
                        chunk = await stream.read(1024)
                        if not chunk:
                            break
                        output_chunks.append(chunk.decode("utf-8", errors="replace"))
                    except Exception:
                        break

            read_task = asyncio.create_task(_read_stream(p.stdout))
            try:
                await asyncio.wait_for(p.wait(), timeout=float(timeout))
                if read_task:
                    try:
                        await asyncio.wait_for(read_task, timeout=2.0)
                    except asyncio.TimeoutError:
                        pass
                res = process_carriage_returns(strip_ansi("".join(output_chunks)))
                if not res.strip():
                    return "Command executed with no output."
                return truncate_output(res, max_chars=4000, hint="Pipe output to grep/head/tail if complete log is needed.", tool_name="shell", from_end=True)
            except asyncio.TimeoutError:
                await terminate_process(p)
                if read_task:
                    try:
                        await asyncio.wait_for(read_task, timeout=1.0)
                    except Exception:
                        pass
                raw_out = process_carriage_returns(strip_ansi("".join(output_chunks)))
                partial_str = f"\n\nPartial Output:\n{raw_out.strip()}" if raw_out.strip() else ""
                return f"Error: Command timed out after {timeout} seconds and was terminated.{partial_str}"
            except asyncio.CancelledError:
                await terminate_process(p)
                raise

        task_id = _new_task_id()
        target_widget = getattr(ctx.app, "current_tool_widget", None) if ctx.app else None
        task = BackgroundTask(
            task_id,
            cmd,
            p,
            widget=target_widget,
        )
        callback = getattr(ctx.app, "on_background_shell_completed", None) if ctx.app else None

        if run_in_bg:
            task.is_background = True
            ctx.add_background_task(task)
            task.start_reading(ctx.app, callback)
            if ctx.app:
                ctx.notify(f"Command sent to background (TID: {task_id})")
            return (
                f"[Background Task ID: {task_id}] Command is running in background.\n\nRecent Output: (No output yet)\n\n"
                "Note: If Recent Output shows an interactive prompt (e.g. asking for input, confirmation [y/N], password, or 'Press RETURN'), "
                f"you may call manage_task(action='send_input', task_id='{task_id}', input='...') to answer it, or manage_task(action='kill', task_id='{task_id}') to abort. "
                "Otherwise, STOP calling tools in a loop, inform the user that the command is running in the background, and end your turn."
            )

        ctx.add_background_task(task)
        task.start_reading(ctx.app, callback)

        try:
            wait_proc_task = asyncio.ensure_future(p.wait())
            wait_bg_task = asyncio.ensure_future(task.background_event.wait())
            done, pending = await asyncio.wait(
                [wait_proc_task, wait_bg_task],
                timeout=float(timeout),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t_pending in pending:
                t_pending.cancel()

            if not done:
                raise asyncio.TimeoutError()

            if task.background_event.is_set() or task.is_background:
                task.is_background = True
                if ctx.app:
                    ctx.notify(f"Command sent to background (TID: {task_id})")
                raw_out = task.get_formatted_output()
                if raw_out.strip():
                    if len(raw_out) > 2000:
                        out_tail = "... [Output truncated, showing last 2000 chars]\n" + raw_out[-2000:]
                    else:
                        out_tail = raw_out
                    recent_output_str = f"\n\nRecent Output:\n{out_tail}"
                else:
                    recent_output_str = "\n\nRecent Output: (No output yet)"
                return (
                    f"[Background Task ID: {task_id}] Command is running in background.{recent_output_str}\n\n"
                    "Note: If Recent Output shows an interactive prompt (e.g. asking for input, confirmation [y/N], password, or 'Press RETURN'), "
                    f"you may call manage_task(action='send_input', task_id='{task_id}', input='...') to answer it, or manage_task(action='kill', task_id='{task_id}') to abort. "
                    "Otherwise, STOP calling tools in a loop, inform the user that the command is running in the background, and end your turn."
                )

            if task.read_task:
                try:
                    await asyncio.wait_for(task.read_task, timeout=2.0)
                except asyncio.TimeoutError:
                    pass
            task.close_pty()
            res = task.get_formatted_output()
            if not res.strip():
                return "Command executed with no output."
            return truncate_output(res, max_chars=4000, hint="Pipe output to grep/head/tail if complete log is needed.", tool_name="shell", from_end=True)
        except asyncio.TimeoutError:
            task.is_background = True
            if ctx.app:
                ctx.notify(f"Command sent to background (TID: {task_id})")
            raw_out = task.get_formatted_output()
            if raw_out.strip():
                if len(raw_out) > 2000:
                    out_tail = "... [Output truncated, showing last 2000 chars]\n" + raw_out[-2000:]
                else:
                    out_tail = raw_out
                recent_output_str = f"\n\nRecent Output:\n{out_tail}"
            else:
                recent_output_str = "\n\nRecent Output: (No output yet)"
            return (
                f"[Background Task ID: {task_id}] Command is running in background.{recent_output_str}\n\n"
                "Note: If Recent Output shows an interactive prompt (e.g. asking for input, confirmation [y/N], password, or 'Press RETURN'), "
                f"you may call manage_task(action='send_input', task_id='{task_id}', input='...') to answer it, or manage_task(action='kill', task_id='{task_id}') to abort. "
                "Otherwise, STOP calling tools in a loop, inform the user that the command is running in the background, and end your turn."
            )
        except asyncio.CancelledError:
            if 'task' in locals() and task:
                task.kill_sync()
                task.close_pty()
            elif 'p' in locals() and p:
                try:
                    p.kill()
                except Exception:
                    pass
            raise

    async def _create_std_process(self, command: str, env: dict[str, str]):
        if is_windows():
            return await self._create_windows_process(command, env)
        return await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            executable=shell_executable(),
            **shell_subprocess_kwargs(),
        )

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
