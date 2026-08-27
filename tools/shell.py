import asyncio
import itertools
import logging
import platform
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

logger = logging.getLogger(__name__)

_TASK_ID_COUNTER = itertools.count(1)


def _sandbox_fallback_notice(ctx: Any) -> str:
    """Banner appended to results when sandboxing was requested but unavailable.

    Subagents and read-only roles rely on sandbox policy; silently running with
    full access would be a false sense of safety, so we surface the degradation.
    """
    if not getattr(ctx, "sandbox_enabled", False):
        return ""
    try:
        from core.infrastructure.platform.sandbox import is_sandbox_supported

        if is_sandbox_supported():
            return ""
    except Exception:
        pass
    logger.warning("sandbox enabled but no usable backend on %s; command ran unsandboxed", platform.system())
    return "[sandbox unavailable on this platform: executed unsandboxed]\n"


def _new_task_id() -> str:
    return f"shell_{time.time_ns()}_{next(_TASK_ID_COUNTER)}"


def _attach_shell_widget(host, task_id: str, widget) -> None:
    """Link the shell tool card to the task for the completion repaint.

    Live chunks stream to the card through the task's output listeners; this
    registry only keeps a handle so the host can flip the card to its terminal
    status (spinner -> done/error) once the task exits.
    """
    if host is None or widget is None:
        return
    setattr(widget, "background_task_id", task_id)
    reg = getattr(host, "_background_shell_widgets", None)
    if reg is None:
        reg = host._background_shell_widgets = {}
    reg[task_id] = widget


def _format_background_task_response(
    task_id: str,
    cmd: str,
    recent_output_str: str = None,
    log_path: str = None,
    by_user: bool = False,
    elapsed: float = None,
) -> str:
    """Formats a background task status response."""
    log_hint = f"\nFull Log: {log_path} (live; inspect via tail/grep)" if log_path else ""
    suffix = f" by user after {elapsed}s" if by_user and elapsed is not None else (" by user" if by_user else "")
    if recent_output_str is None:
        return f"[Background Task ID: {task_id}] '{cmd}' moved to background{suffix}.{log_hint}"
    return f"[Background Task ID: {task_id}] '{cmd}' moved to background{suffix}.{recent_output_str}{log_hint}"


def _truncate_output(res: str) -> str:
    return truncate_output(
        res,
        max_chars=4000,
        tool_name="shell",
        from_end=True,
    )


class ShellTool(BaseTool):
    name = "shell"
    description = (
        "Execute non-interactive shell command. ALWAYS specify explicit path (e.g. 'rg foo .') "
        "to avoid stdin hang. Set background=true for servers/long jobs. Use unbuffered output "
        "(flush/flags) for long scripts, loops, and streaming logs. Manage, send stdin, or kill via 'manage_shell'."
    )

    schema = {
        "type": "function",
        "function": {
            "name": "shell",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to run",
                    },
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default: 120, max: 600)"},
                    "background": {
                        "type": "boolean",
                        "description": (
                            "Run in background. Returns task_id and live log path; "
                            "completion notifies automatically (default: false)"
                        ),
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
        if not cmd:
            return ToolResult.error("params", name="command", detail="missing or empty")

        raw_timeout = args.get("timeout", 120)
        try:
            timeout = max(1, min(int(raw_timeout), 600))
        except (ValueError, TypeError):
            timeout = 120

        env = shell_env()
        proc_cwd = ctx.cwd if isinstance(getattr(ctx, "cwd", None), str) else None
        sandbox_enabled = bool(getattr(ctx, "sandbox_enabled", False))
        allow_workspace_writes = not bool(getattr(ctx, "is_read_only", False))
        p = await self._create_std_process(
            cmd,
            env,
            cwd=proc_cwd,
            sandbox_enabled=sandbox_enabled,
            allow_workspace_writes=allow_workspace_writes,
        )

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
            res = await self._run_sync(p, ctx, cmd, timeout)
            notice = _sandbox_fallback_notice(ctx)
            if notice and res.content:
                res.content = notice + res.content
            return res

        # Explicit background execution (main agent only).
        task_id = _new_task_id()
        task = ShellTask(
            task_id,
            cmd,
            p,
            session_id=ctx.session_id,
        )
        target_widget = getattr(ctx.host, "current_tool_widget", None) if ctx.host else None
        if target_widget is not None:
            task.add_listener(target_widget.append_shell_output)
        _attach_shell_widget(ctx.host, task_id, target_widget)
        callback = getattr(ctx.host, "on_background_shell_completed", None) if ctx.host else None
        task.is_background = True
        task.open_log()
        ctx.add_background_task(task)
        task.start_reading(on_completed=callback)

        xml_content = f'<bg_task id="{task_id}" log="{task.log_path}" status="running"/>'
        disp_content = _format_background_task_response(task_id, cmd, log_path=task.log_path)
        notice = _sandbox_fallback_notice(ctx)
        if notice:
            disp_content = notice + disp_content
        return ToolResult(status=ToolResultStatus.RUNNING, content=xml_content, display=disp_content)

    async def _run_sync(self, p: Any, ctx: Any, cmd: str, timeout: int) -> ToolResult:
        """Run a process synchronously: stream output into a bounded tail buffer,
        wait with a hard timeout, terminate the process on timeout/cancellation.
        Never converts to a background task unless ctrl+b / background_event is triggered.
        """
        task_id = _new_task_id()
        task = ShellTask(
            task_id,
            cmd,
            p,
            session_id=ctx.session_id,
        )
        target_widget = getattr(ctx.host, "current_tool_widget", None) if ctx.host else None
        if target_widget is not None:
            task.add_listener(target_widget.append_shell_output)
        _attach_shell_widget(ctx.host, task_id, target_widget)
        callback = getattr(ctx.host, "on_background_shell_completed", None) if ctx.host else None
        ctx.add_background_task(task)
        read_task = task.start_reading(on_completed=callback)

        start_time = time.monotonic()
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
                elapsed = max(0.1, round(time.monotonic() - start_time, 1))
                raw_out = task.get_formatted_output().strip()
                recent_str = f"\n\nRecent Output:\n{tail_output(raw_out, max_chars=2000)}" if raw_out else None
                xml_content = f'<bg_task id="{task_id}" log="{task.log_path}" status="running" elapsed="{elapsed}s"/>'
                return ToolResult(
                    status=ToolResultStatus.RUNNING,
                    content=xml_content,
                    display=_format_background_task_response(
                        task_id,
                        cmd,
                        recent_output_str=recent_str,
                        log_path=task.log_path,
                        by_user=True,
                        elapsed=elapsed,
                    ),
                )

            if read_task:
                try:
                    await asyncio.wait_for(read_task, timeout=2.0)
                except asyncio.TimeoutError:
                    pass
            elapsed = max(0.1, round(time.monotonic() - start_time, 1))
            res = task.get_formatted_output()
            raw_rc = p.returncode if p.returncode is not None else getattr(task, "returncode", None)
            returncode = raw_rc if isinstance(raw_rc, int) else None
            rc_attr = f' exit="{returncode}"' if returncode is not None else ' exit="0"'
            elapsed_attr = f' elapsed="{elapsed}s"'
            if not res.strip():
                xml_content = f"<cmd{rc_attr}{elapsed_attr}/>"
                disp = f"(exit code {returncode})" if (returncode is not None and returncode != 0) else "(no output)"
                return ToolResult.done(content=xml_content, display=disp, returncode=returncode)
            truncated = _truncate_output(res)
            xml_content = f"<cmd{rc_attr}{elapsed_attr}>\n{truncated.strip()}\n</cmd>"
            return ToolResult.done(content=xml_content, display=truncated, returncode=returncode)
        except asyncio.TimeoutError:
            await terminate_process(p)
            if read_task:
                try:
                    await asyncio.wait_for(read_task, timeout=1.0)
                except Exception:
                    pass
            raw_out = _truncate_output(task.get_formatted_output())
            partial_str = f"\n<cmd>\n{raw_out.strip()}\n</cmd>" if raw_out.strip() else ""
            disp_partial = f"\n\nPartial Output:\n{raw_out.strip()}" if raw_out.strip() else ""
            disp = f"ERR: timeout 'shell': timed out after {timeout}s{disp_partial}"
            return ToolResult.error("timeout", f"timed out after {timeout}s{partial_str}", name="shell", display=disp)
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

    async def _create_std_process(
        self,
        command: str,
        env: dict[str, str],
        cwd: str = None,
        sandbox_enabled: bool = False,
        allow_workspace_writes: bool = True,
    ):
        if sandbox_enabled:
            from core.infrastructure.platform.sandbox import build_sandboxed_command

            exe, args, is_sandboxed = build_sandboxed_command(
                command, cwd=cwd, allow_workspace_writes=allow_workspace_writes
            )
            if is_sandboxed:
                return await asyncio.create_subprocess_exec(
                    exe,
                    *args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=env,
                    cwd=cwd,
                    **shell_subprocess_kwargs(),
                )
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
            full_command = (
                f"$OutputEncoding = [System.Text.Encoding]::UTF8; "
                f"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
                f"{command}"
            )
            return await asyncio.create_subprocess_exec(
                shell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                full_command,
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
