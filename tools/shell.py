import asyncio
import logging
import platform
import time
import uuid
from typing import Any, Dict

from core.domain.defaults.config import DEFAULT_SHELL_MAX_CAP, DEFAULT_SHELL_TIMEOUT
from core.domain.defaults.errors import ToolResult, ToolResultStatus
from core.infrastructure.platform.platform_utils import (
    is_windows,
    shell_env,
    shell_executable,
    shell_subprocess_kwargs,
    terminate_process,
)
from core.infrastructure.tasks.shell_task import ShellTask
from tools.base import BaseTool, truncate_output

logger = logging.getLogger(__name__)


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
    return "[sandbox unavailable | executed unsandboxed]\n"


def _new_task_id() -> str:
    return f"shell-{uuid.uuid4().hex[:4]}"


def _attach_shell_widget(host, task_id: str, widget, log_path: str = None) -> None:
    """Link the shell tool card to the task for the completion repaint.

    Live chunks stream to the card through the task's output listeners; this
    registry only keeps a handle so the host can flip the card to its terminal
    status (spinner -> done/error) once the task exits.
    """
    if host is None or widget is None:
        return
    setattr(widget, "background_task_id", task_id)
    if log_path:
        setattr(widget, "log_path", log_path)
    reg = getattr(host, "_background_shell_widgets", None)
    if reg is None:
        reg = host._background_shell_widgets = {}
    reg[task_id] = widget


def _truncate_output(res: str) -> str:
    from core.infrastructure.config.settings import get_settings

    return truncate_output(
        res,
        max_chars=get_settings().tools.max_shell_output_chars,
        tool_name="shell",
        from_end=True,
    )


class ShellTool(BaseTool):
    name = "shell"
    description = (
        "Execute a NON-INTERACTIVE shell command. ALWAYS specify explicit path (e.g. 'rg foo .') "
        "to avoid stdin hang. Set background=true for servers/long jobs. Use unbuffered output "
        "(flush/flags) for long scripts, loops, and streaming logs. Manage, send stdin, or kill via 'manage_shell'."
    )

    schema = {
        "type": "function",
        "function": {
            "name": "shell",
            "description": (
                "Execute a NON-INTERACTIVE shell command synchronously. Output: `[exit N]` line "
                "followed by stdout/stderr; truncated past `max_shell_output_chars` with "
                "`[truncated | log <p> | next read(path=<log>, start_line=N)]` footer.\n\n"
                "Anti-patterns (will hang or fail):\n"
                "- Interactive REPLs: `python -i`, `node`, `irb`, `psql` without `-c`, etc.\n"
                "- Pagers: `less`, `more`, `vim`, `nano`. For sync inspection use `cat` or pipe to `head`/`tail`. "
                "NEVER pipe background commands (`background=true`) to `tail`/`head` — runtime streams full log to disk "
                "and tails notification automatically; piping blocks live stream and triggers false inactivity alerts.\n"
                "- Commands that read stdin without explicit input: `fzf`, `ssh` without `-o BatchMode=yes`.\n"
                "- Stdout buffering: pipes and non-Python tools buffer output in 4KB blocks. "
                "Use unbuffered flags (e.g. `stdbuf -oL`, `grep --line-buffered`) for live logs. Python is auto-unbuffered.\n"
                "Always pass non-interactive flags: `-y` (apt), `--non-interactive`, `--batch`, `-c '<query>'`.\n\n"
                "Environment:\n"
                "- Runs in cwd (from <environment>); subagent cwd is its worktree root.\n"
                "- `manage_shell` is unavailable in subagents (tool removed).\n"
                "- `background=true` is rejected in subagents (sync-only).\n"
                "- If sandbox backend unavailable, runs unsandboxed with `[sandbox unavailable]` banner.\n\n"
                "Error kinds: `timeout` (process killed, NOT backgrounded), `http_status`/etc. don't apply; "
                "use `not_found` for `command not found` (exit 127), `permission` for `Permission denied`."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Non-interactive shell command. NO interactive REPLs or paginators.",
                    },
                    "timeout": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": int(DEFAULT_SHELL_MAX_CAP),
                        "default": int(DEFAULT_SHELL_TIMEOUT),
                        "description": (
                            "Seconds before SIGTERM. For sync commands: defaults to 30s. "
                            "For background=true: hard kill limit (omit or 0 for unlimited runtime)."
                        ),
                    },
                    "idle_timeout": {
                        "type": "integer",
                        "minimum": 0,
                        "default": 30,
                        "description": (
                            "Seconds of stdout silence in background before sending progress "
                            "<notification status='running' event='inactivity'>. 0 to disable."
                        ),
                    },
                    "background": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Run as background task (also triggered when user presses Ctrl+B). "
                            "Returns task_id + log path. Process continues in background. "
                            "Runtime automatically resumes turn with <notification type='shell'> on finish — "
                            "NEVER re-run the command, NEVER poll manage_shell(list) to wait. Main agent only."
                        ),
                    },
                },
                "required": ["command"],
            },
        },
    }

    def get_schema(self, is_subagent: bool = False) -> Dict[str, Any]:
        import copy

        if is_subagent:
            from core.roles.tools import _rebuild_tool

            base_s = _rebuild_tool(self.schema)
        else:
            base_s = copy.deepcopy(self.schema)

        try:
            from core.infrastructure.config.settings import get_settings

            tools_cfg = get_settings().tools
            props = base_s.get("function", {}).get("parameters", {}).get("properties", {})
            if "timeout" in props:
                props["timeout"]["default"] = int(tools_cfg.shell_default_timeout)
                props["timeout"]["maximum"] = int(tools_cfg.shell_max_cap)
        except Exception:
            pass
        return base_s

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        from core.infrastructure.config.settings import get_settings

        settings = get_settings()
        args = args or {}
        ctx = self._ensure_context(ctx)
        cmd = (args.get("command") or "").strip()
        if not cmd:
            return ToolResult.error("params", name="command", detail="missing or empty")

        default_timeout = settings.tools.shell_default_timeout
        max_cap = settings.tools.shell_max_cap
        raw_timeout = args.get("timeout", default_timeout)
        try:
            timeout = max(1, min(int(raw_timeout), max_cap))
        except (ValueError, TypeError):
            timeout = default_timeout

        idle_raw = args.get("idle_timeout", 30)
        try:
            idle_timeout = max(0, int(idle_raw))
        except (ValueError, TypeError):
            idle_timeout = 30

        run_in_bg = bool(args.get("background", False))
        if run_in_bg and ctx.is_subagent:
            return ToolResult.error("background", name="shell")

        hard_timeout = None
        if run_in_bg and "timeout" in args and args.get("timeout") is not None:
            try:
                t_val = int(args["timeout"])
                if t_val > 0:
                    hard_timeout = max(1, min(t_val, max_cap))
            except (ValueError, TypeError):
                hard_timeout = None

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

        # Synchronous execution mode (default for main and subagents): stream
        # output into a bounded tail buffer and wait with a hard timeout. On
        # timeout the process is terminated (never converted to a background
        # task), so long-running commands report a truthful error instead of
        # silently continuing after the agent already returns.
        if not run_in_bg:
            res = await self._run_sync(p, ctx, cmd, timeout, idle_timeout=idle_timeout)
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
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
        )
        target_widget = getattr(ctx.host, "current_tool_widget", None) if ctx.host else None
        if target_widget is not None:
            task.add_listener(target_widget.append_shell_output)
        callback = getattr(ctx.host, "on_background_shell_completed", None) if ctx.host else None
        progress_cb = getattr(ctx.host, "on_background_shell_progress", None) if ctx.host else None
        task.is_background = True
        # Open the log BEFORE attaching so the widget/registry receive the real
        # log path (task.log_path is only populated by open_log()).
        task.open_log()
        _attach_shell_widget(ctx.host, task_id, target_widget, log_path=task.log_path)
        ctx.add_background_task(task)
        task.start_reading(on_completed=callback, on_progress=progress_cb)

        plain_content = f"[task started | id {task_id} | log {task.log_path}]"
        notice = _sandbox_fallback_notice(ctx)
        if notice:
            plain_content = notice + plain_content
        return ToolResult(status=ToolResultStatus.RUNNING, content=plain_content)

    async def _run_sync(
        self, p: Any, ctx: Any, cmd: str, timeout: int, idle_timeout: int = 30
    ) -> ToolResult:
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
            idle_timeout=idle_timeout,
            hard_timeout=None,
        )
        target_widget = getattr(ctx.host, "current_tool_widget", None) if ctx.host else None
        if target_widget is not None:
            task.add_listener(target_widget.append_shell_output)
        _attach_shell_widget(ctx.host, task_id, target_widget)
        callback = getattr(ctx.host, "on_background_shell_completed", None) if ctx.host else None
        progress_cb = getattr(ctx.host, "on_background_shell_progress", None) if ctx.host else None
        ctx.add_background_task(task)
        read_task = task.start_reading(on_completed=callback, on_progress=progress_cb)

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
                task.move_to_background()
                if target_widget is not None and task.log_path:
                    setattr(target_widget, "log_path", task.log_path)
                elapsed = max(0.1, round(time.monotonic() - start_time, 1))
                raw_out = task.get_formatted_output().strip()
                if raw_out:
                    truncated = truncate_output(
                        raw_out, max_chars=2000, tool_name="shell", save_log=False, from_end=True
                    ).strip()
                    plain_content = (
                        f"[task backgrounded by user | id {task_id} | log {task.log_path} | elapsed {elapsed}s | wait for notification]\n\n"
                        f"{truncated}"
                    )
                else:
                    plain_content = (
                        f"[task backgrounded by user | id {task_id} | log {task.log_path} | elapsed {elapsed}s | no output yet (buffered) | wait for notification]"
                    )
                return ToolResult(
                    status=ToolResultStatus.RUNNING,
                    content=plain_content,
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
            if not res.strip():
                content_str = f"[exit {returncode}]" if (returncode is not None and returncode != 0) else "[no output]"
                return ToolResult.done(content=content_str, display=content_str, returncode=returncode)
            truncated = _truncate_output(res).strip()
            return ToolResult.done(content=truncated, display=truncated, returncode=returncode)
        except asyncio.TimeoutError:
            await terminate_process(p)
            if read_task and not read_task.done():
                read_task.cancel()
                try:
                    # CancelledError is a BaseException since py3.8 and is not
                    # caught by `except Exception`; swallowing the expected
                    # cancellation of the stdout reader is required.
                    await asyncio.wait_for(read_task, timeout=0.2)
                except (asyncio.CancelledError, Exception):
                    pass
            raw_out = _truncate_output(task.get_formatted_output()).strip()
            partial_str = f"\n\n{raw_out}" if raw_out else ""
            disp = f"ERR: timeout 'shell': timed out after {timeout}s{partial_str}"
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
