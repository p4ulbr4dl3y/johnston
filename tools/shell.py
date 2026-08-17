import asyncio
import itertools
import re
import time
from typing import Any, Dict

from core.domain.defaults.errors import ToolResult, ToolResultStatus
from core.infrastructure.platform.platform_utils import (
    is_windows,
    shell_env,
    shell_executable,
    shell_subprocess_kwargs,
    terminate_process,
)
from core.infrastructure.tasks.output import tail_output
from core.infrastructure.tasks.shell_task import ShellTask
from tools.base import BaseTool, truncate_output

SLEEP_CHAIN_REGEX = re.compile(r"^sleep\s+([0-9]+(?:\.[0-9]+)?)\s*(?:(?:&&|;)\s*(.*))?$", re.DOTALL)
_TASK_ID_COUNTER = itertools.count(1)


def _new_task_id() -> str:
    return f"shell_{time.time_ns()}_{next(_TASK_ID_COUNTER)}"


def _format_background_task_response(
    task_id: str, cmd: str, recent_output_str: str = None, log_path: str = None
) -> str:
    """Formats a background task status response."""
    log_hint = f"\nFull Log: {log_path} (live; inspect via tail/grep)" if log_path else ""
    if recent_output_str is None:
        return f"[Background Task ID: {task_id}] '{cmd}' moved to background.{log_hint}"
    return f"[Background Task ID: {task_id}] '{cmd}' moved to background.{recent_output_str}{log_hint}"


def _truncate_output(res: str) -> str:
    return truncate_output(
        res,
        max_chars=4000,
        hint="Pipe output to grep/head/tail if complete log is needed.",
        tool_name="shell",
        from_end=True,
    )


class ShellTool(BaseTool):
    name = "shell"
    description = "Run a terminal command synchronously or in the background (background: true)."

    schema = {
        "type": "function",
        "function": {
            "name": "shell",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Terminal command to run (relative to cwd)",
                    },
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 120, max 600)"},
                    "background": {
                        "type": "boolean",
                        "description": "Run asynchronously in background; completion arrives via System Notification",
                    },
                },
                "required": ["command"],
            },
        },
    }

    def get_schema(self, is_subagent: bool = False) -> Dict[str, Any]:
        if not is_subagent:
            return self.schema
        from core.roles.tools import _rebuild_tool

        return _rebuild_tool(self.schema)

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        args = args or {}
        ctx = self._ensure_context(ctx)
        cmd = (args.get("command") or "").strip()

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
                return ToolResult.error("reject", detail=f"sleep {sec}s exceeds timeout {timeout}s")
            await asyncio.sleep(sec)
            if not remainder:
                return ToolResult.done(f"slept {sec}s")
            cmd = remainder

        env = shell_env()
        proc_cwd = ctx.cwd if isinstance(getattr(ctx, "cwd", None), str) else None
        p = await self._create_std_process(cmd, env, cwd=proc_cwd)

        run_in_bg = bool(args.get("background", False))
        if run_in_bg and ctx.is_subagent:
            await terminate_process(p)
            return ToolResult.error("background", name="shell")

        # Synchronous execution mode (default for main and subagents): stream
        # output into a bounded tail buffer and wait with a hard timeout. On
        # timeout the process is terminated (never converted to a background
        # task), so long-running commands report a truthful error instead of
        # silently continuing after the agent already returns.
        if not run_in_bg:
            return await self._run_sync(p, ctx, cmd, timeout)

        # Explicit background execution (main agent only).
        task_id = _new_task_id()
        target_widget = getattr(ctx.host, "current_tool_widget", None) if ctx.host else None
        task = ShellTask(
            task_id,
            cmd,
            p,
            widget=target_widget,
            session_id=ctx.session_id,
        )
        callback = getattr(ctx.host, "on_background_shell_completed", None) if ctx.host else None
        task.is_background = True
        task.open_log()
        ctx.add_background_task(task)
        task.start_reading(on_completed=callback)

        return ToolResult(status=ToolResultStatus.RUNNING, content=_format_background_task_response(task_id, cmd, log_path=task.log_path))

    async def _run_sync(self, p: Any, ctx: Any, cmd: str, timeout: int) -> ToolResult:
        """Run a process synchronously: stream output into a bounded tail buffer,
        wait with a hard timeout, terminate the process on timeout/cancellation.
        Never converts to a background task unless ctrl+b / background_event is triggered.
        """
        task_id = _new_task_id()
        target_widget = getattr(ctx.host, "current_tool_widget", None) if ctx.host else None
        task = ShellTask(
            task_id,
            cmd,
            p,
            widget=target_widget,
            session_id=ctx.session_id,
        )
        callback = getattr(ctx.host, "on_background_shell_completed", None) if ctx.host else None
        ctx.add_background_task(task)
        read_task = task.start_reading(on_completed=callback)

        proc_task = asyncio.ensure_future(p.wait())
        bg_task = asyncio.ensure_future(task.background_event.wait())

        try:
            done, pending = await asyncio.wait(
                [proc_task, bg_task],
                timeout=float(timeout),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

            if not done:
                raise asyncio.TimeoutError()

            if task.background_event.is_set() or getattr(task, "is_background", False):
                task.is_background = True
                task.open_log()
                raw_out = task.get_formatted_output().strip()
                recent_str = f"\n\nRecent Output:\n{tail_output(raw_out, max_chars=2000)}" if raw_out else None
                return ToolResult(
                    status=ToolResultStatus.RUNNING,
                    content=_format_background_task_response(
                        task_id, cmd, recent_output_str=recent_str, log_path=task.log_path
                    ),
                )

            if read_task:
                try:
                    await asyncio.wait_for(read_task, timeout=2.0)
                except asyncio.TimeoutError:
                    pass
            res = task.get_formatted_output()
            if not res.strip():
                return ToolResult.done("(no output)")
            return ToolResult.done(_truncate_output(res))
        except asyncio.TimeoutError:
            await terminate_process(p)
            if read_task:
                try:
                    await asyncio.wait_for(read_task, timeout=1.0)
                except Exception:
                    pass
            raw_out = _truncate_output(task.get_formatted_output())
            partial_str = f"\n\nPartial Output:\n{raw_out.strip()}" if raw_out.strip() else ""
            return ToolResult.error("timeout", f"timed out after {timeout}s{partial_str}", name="shell")
        except asyncio.CancelledError:
            await terminate_process(p)
            raise
        finally:
            if not getattr(task, "is_background", False):
                mgr = getattr(ctx, "task_manager", None)
                if mgr is not None and hasattr(mgr, "drop"):
                    try:
                        mgr.drop(task.task_id)
                    except Exception:
                        pass

    async def _create_std_process(self, command: str, env: dict[str, str], cwd: str = None):
        if is_windows():
            return await self._create_windows_process(command, env, cwd=cwd)
        return await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=cwd,
            executable=shell_executable(),
            **shell_subprocess_kwargs(),
        )

    async def _create_windows_process(self, command: str, env: dict[str, str], cwd: str = None):
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
                cwd=cwd,
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
                cwd=cwd,
                **shell_subprocess_kwargs(),
            )
        return await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=cwd,
            **shell_subprocess_kwargs(),
        )
