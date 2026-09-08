import asyncio
import logging
import os
import platform
import time
import uuid
from typing import Any, Dict, Optional

from johnston_core.domain.defaults.config import (
    DEFAULT_SHELL_IDLE_TIMEOUT,
    DEFAULT_SHELL_MAX_CAP,
    DEFAULT_SHELL_TIMEOUT,
)
from johnston_core.domain.defaults.errors import ToolResult, ToolResultStatus
from johnston_core.domain.policies.policy_shell import check_read_only_command_mutations
from johnston_core.infrastructure.platform.command_sanitizer import clean_cd_command
from johnston_core.infrastructure.platform.platform_utils import (
    is_windows,
    shell_env,
    shell_executable,
    terminate_process,
)
from johnston_core.infrastructure.platform.process import spawn_shell_process, spawn_windows_process
from johnston_core.infrastructure.tasks.shell_task import ShellTask
from johnston_core.tools.base import BaseTool, resolve_path, truncate_output

logger = logging.getLogger(__name__)


def _sandbox_fallback_notice(ctx: Any) -> str:
    """Banner appended to results when sandboxing was requested but unavailable.

    Subagents and read-only roles rely on sandbox policy; silently running with
    full access would be a false sense of safety, so we surface the degradation.
    """
    if not getattr(ctx, "sandbox_enabled", False):
        return ""
    try:
        from johnston_core.infrastructure.platform.sandbox import is_sandbox_supported

        if is_sandbox_supported():
            return ""
    except Exception:
        pass
    logger.warning("sandbox enabled but no usable backend on %s; command ran unsandboxed", platform.system())
    return "[sandbox unavailable | executed unsandboxed]\n"


def _new_task_id() -> str:
    return f"shell-{uuid.uuid4().hex[:4]}"


def _promote_task_to_background(
    task: ShellTask,
    ctx: Any,
    target_widget: Any = None,
) -> None:
    """Move task to background, register it in context, attach widget and update session."""
    task.move_to_background()
    ctx.add_background_task(task)
    if target_widget is not None and not getattr(ctx, "is_subagent", False):
        ctx.attach_shell_widget(task.task_id, target_widget, log_path=task.log_path, is_background=True)
    if getattr(ctx, "session", None) and hasattr(ctx.session, "messages"):
        for msg in reversed(ctx.session.messages):
            if isinstance(msg, dict) and msg.get("type") == "tool" and msg.get("tool_type") == "shell":
                msg["task_id"] = task.task_id
                msg["background_task_id"] = task.task_id
                if task.log_path:
                    msg["log_path"] = task.log_path
                break


def _attach_shell_widget(
    host: Any,
    task_id: str,
    widget: Any,
    log_path: str | None = None,
    is_background: bool = False,
) -> None:
    """Link the shell tool card to the task for the completion repaint."""
    from johnston_core.tools.context import ToolContext

    ToolContext(app=host).attach_shell_widget(
        task_id=task_id,
        widget=widget,
        log_path=log_path,
        is_background=is_background,
    )


async def _cancel_read_task(read_task: Optional[asyncio.Task]) -> None:
    """Safely cancel stdout reader task, swallowing CancelledError."""
    if read_task and not read_task.done():
        read_task.cancel()
        try:
            await asyncio.wait_for(read_task, timeout=0.2)
        except (asyncio.CancelledError, Exception):
            pass



def _truncate_output(res: str) -> str:
    from johnston_core.infrastructure.config.settings import get_settings

    return truncate_output(
        res,
        max_chars=get_settings().tools.max_shell_output_chars,
        tool_name="shell",
        from_end=True,
    )


_clean_cd_command = clean_cd_command

_check_read_only_command_mutations = check_read_only_command_mutations



class ShellTool(BaseTool):
    name = "shell"
    description = (
        "Execute a non-interactive shell command synchronously or with background execution. "
        "Runs in project root by default (use 'cwd' for subdirectories, never 'cd'). "
        "Always use non-interactive flags (e.g. -y, --batch). Outputs [exit N] followed by stdout/stderr."
    )

    schema = {
        "type": "function",
        "function": {
            "name": "shell",
            "description": (
                "Execute a non-interactive shell command synchronously or with background execution. "
                "Runs in project root by default (use 'cwd' for subdirectories, never 'cd'). "
                "Always use non-interactive flags (e.g. -y, --batch). Outputs [exit N] followed by stdout/stderr."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": (
                            "Non-interactive shell command to execute. Do not launch interactive pagers or REPLs."
                        ),
                    },
                    "cwd": {
                        "type": "string",
                        "description": (
                            "Directory to run command in (default: current workspace root). "
                            "Always use this parameter instead of 'cd'. "
                            "Omit if working in project root."
                        ),
                    },
                    "timeout": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": int(DEFAULT_SHELL_MAX_CAP),
                        "default": int(DEFAULT_SHELL_TIMEOUT),
                        "description": (
                            f"Seconds before SIGTERM. For sync commands: defaults to {int(DEFAULT_SHELL_TIMEOUT)}s. "
                            "For background commands (wait_seconds specified): hard kill limit (omit or 0 for unlimited runtime)."
                        ),
                    },
                    "wait_seconds": {
                        "type": "integer",
                        "minimum": 0,
                        "description": (
                            "Synchronous wait threshold in seconds before moving to background. "
                            "Omit (or null) to run synchronously up to timeout (never backgrounded). "
                            "0 = run in background immediately without idle alerts (persistent servers, daemons, watchers). "
                            "N > 0 = wait up to N seconds (builds, tests, migrations): returns output immediately if finished; "
                            "otherwise moves to background task with hang detection. "
                            "Main agent only. When backgrounded, do not poll or sleep; runtime sends <notification> on exit or inactivity."
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
            from johnston_core.roles.tools import _rebuild_tool

            base_s = _rebuild_tool(self.schema)
        else:
            base_s = copy.deepcopy(self.schema)

        try:
            from johnston_core.infrastructure.config.settings import get_settings

            tools_cfg = get_settings().tools
            props = base_s.get("function", {}).get("parameters", {}).get("properties", {})
            if "timeout" in props:
                props["timeout"]["default"] = int(tools_cfg.shell_default_timeout)
                props["timeout"]["maximum"] = int(tools_cfg.shell_max_cap)
        except Exception:
            pass
        return base_s

    def is_concurrency_safe(self, args: Dict[str, Any] | None = None) -> bool:
        return False

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        from johnston_core.infrastructure.config.settings import get_settings

        settings = get_settings()
        args = args or {}
        ctx = self._ensure_context(ctx)
        raw_cmd = args.get("command")
        if raw_cmd is None:
            return ToolResult.error("params", name="command", detail="missing or empty")
        cmd = str(raw_cmd).strip()
        if not cmd:
            return ToolResult.error("params", name="command", detail="missing or empty")

        workspace_dir = (
            ctx.cwd
            if isinstance(getattr(ctx, "cwd", None), str) and ctx.cwd
            else os.getcwd()
        )
        workspace_dir = os.path.realpath(os.path.abspath(workspace_dir))

        cmd, cd_err = clean_cd_command(cmd, workspace_dir)
        if cd_err:
            return ToolResult.error("params", name="command", detail=cd_err)
        if not cmd:
            return ToolResult.error("params", name="command", detail="missing or empty")

        raw_cwd = args.get("cwd")
        if raw_cwd is not None and str(raw_cwd).strip() not in (".", "./", ".\\", ""):
            resolved_cwd = resolve_path(str(raw_cwd).strip(), cwd=workspace_dir)
            if not os.path.exists(resolved_cwd):
                return ToolResult.error(
                    "not_found",
                    name=str(raw_cwd),
                    detail=f"directory '{raw_cwd}' does not exist",
                )
            if not os.path.isdir(resolved_cwd):
                return ToolResult.error(
                    "params",
                    name=str(raw_cwd),
                    detail=f"path '{raw_cwd}' is not a directory",
                )
            proc_cwd = resolved_cwd
        else:
            proc_cwd = workspace_dir

        allow_workspace_writes = not bool(getattr(ctx, "is_read_only", False))
        if not allow_workspace_writes:
            ro_err = _check_read_only_command_mutations(cmd)
            if ro_err:
                return ToolResult.error("permission", name="shell", detail=ro_err)
        sandbox_enabled = bool(getattr(ctx, "sandbox_enabled", False))
        if sandbox_enabled:
            from johnston_core.infrastructure.platform.sandbox import (
                is_path_readable_in_sandbox,
                is_path_writable_in_sandbox,
                is_sandbox_supported,
            )

            if not allow_workspace_writes and not is_sandbox_supported():
                return ToolResult.error(
                    "sandbox",
                    name="shell",
                    detail="read-only role requires sandbox isolation, but OS sandbox backend is unavailable",
                )

            if not is_path_readable_in_sandbox(proc_cwd, cwd=workspace_dir):
                return ToolResult.error(
                    "permission",
                    name=str(raw_cwd or proc_cwd),
                    detail=f"sandbox restriction: cannot read '{raw_cwd or proc_cwd}'",
                )
            if allow_workspace_writes and not is_path_writable_in_sandbox(proc_cwd, cwd=workspace_dir):
                return ToolResult.error(
                    "permission",
                    name=str(raw_cwd or proc_cwd),
                    detail=f"sandbox restriction: cannot write to '{raw_cwd or proc_cwd}'",
                )

        default_timeout = settings.tools.shell_default_timeout
        max_cap = settings.tools.shell_max_cap
        raw_timeout = args.get("timeout", default_timeout)
        try:
            timeout = max(1, min(int(raw_timeout), max_cap))
        except (ValueError, TypeError):
            timeout = default_timeout

        wait_seconds_raw = args.get("wait_seconds", None)
        wait_seconds = None
        if wait_seconds_raw is not None:
            try:
                wait_seconds = max(0, int(wait_seconds_raw))
            except (ValueError, TypeError):
                wait_seconds = None

        if wait_seconds is not None and not getattr(ctx, "is_interactive", True):
            return ToolResult.error("permission", name="shell", detail="wait_seconds disabled in subagent/headless mode")

        # Auto-derived idle timeout: 0 for persistent services (wait_seconds=0),
        # hang-detection heartbeat for batch tasks (wait_seconds > 0) or user Ctrl+B.
        default_idle = getattr(settings.tools, "shell_idle_timeout", DEFAULT_SHELL_IDLE_TIMEOUT)
        idle_timeout = 0 if wait_seconds == 0 else int(default_idle)

        hard_timeout = None
        if wait_seconds is not None and "timeout" in args and args.get("timeout") is not None:
            try:
                t_val = int(args["timeout"])
                if t_val > 0:
                    hard_timeout = max(1, min(t_val, max_cap))
            except (ValueError, TypeError):
                hard_timeout = None

        env = shell_env()
        p = await self._create_std_process(
            cmd,
            env,
            cwd=proc_cwd,
            workspace_dir=workspace_dir,
            sandbox_enabled=sandbox_enabled,
            allow_workspace_writes=allow_workspace_writes,
        )

        if wait_seconds == 0:
            # Explicit immediate background execution (main agent only).
            task_id = _new_task_id()
            task = ShellTask(
                task_id,
                cmd,
                p,
                session_id=ctx.session_id,
                idle_timeout=idle_timeout,
                hard_timeout=hard_timeout,
            )
            target_widget = ctx.target_tool_widget
            if target_widget is not None:
                task.add_listener(target_widget.append_shell_output)
            if getattr(ctx, "session", None) and hasattr(ctx.session, "add_event"):
                task.add_listener(lambda chunk, tid=task_id: ctx.session.add_event({"type": "tool_shell_output", "text": chunk, "task_id": tid}))
            callback = getattr(ctx.host, "on_background_shell_completed", None) if ctx.host else None
            progress_cb = getattr(ctx.host, "on_background_shell_progress", None) if ctx.host else None
            _promote_task_to_background(task, ctx, target_widget)
            task.start_reading(on_completed=callback, on_progress=progress_cb)

            log_part = f" | log {task.log_path}" if task.log_path else ""
            plain_content = f"[task started | id {task_id}{log_part} | wait for notification]"
            notice = _sandbox_fallback_notice(ctx)
            if notice:
                plain_content = notice + plain_content
            return ToolResult(
                status=ToolResultStatus.RUNNING,
                content=plain_content,
                task_id=task_id,
                background_task_id=task_id,
                log_path=task.log_path,
            )

        # Synchronous execution mode (default or wait_seconds > 0): stream
        # output into a bounded tail buffer. If wait_seconds is specified, wait
        # up to wait_seconds before converting to background; otherwise wait with
        # a hard timeout. On timeout (when wait_seconds is None) the process is
        # terminated (never converted to a background task).
        res = await self._run_sync(
            p,
            ctx,
            cmd,
            timeout,
            idle_timeout=idle_timeout,
            wait_seconds=wait_seconds,
            hard_timeout=hard_timeout,
        )
        notice = _sandbox_fallback_notice(ctx)
        if notice and res.content:
            res.content = notice + res.content
        return res

    async def _run_sync(
        self,
        p: Any,
        ctx: Any,
        cmd: str,
        timeout: int,
        idle_timeout: int = int(DEFAULT_SHELL_IDLE_TIMEOUT),
        wait_seconds: Optional[int] = None,
        hard_timeout: Optional[float] = None,
    ) -> ToolResult:
        """Run a process synchronously: stream output into a bounded tail buffer.

        If wait_seconds is None: wait with hard timeout, terminate on timeout/cancellation.
        Never converts to background task unless ctrl+b / background_event is triggered.

        If wait_seconds is set (N > 0): wait up to wait_seconds; if process doesn't exit,
        converts to background task and returns RUNNING status.
        """
        task_id = _new_task_id()
        task_hard_timeout = (
            float(hard_timeout)
            if hard_timeout is not None
            else (float(timeout) if wait_seconds is None else None)
        )
        task = ShellTask(
            task_id,
            cmd,
            p,
            session_id=ctx.session_id,
            idle_timeout=idle_timeout,
            hard_timeout=task_hard_timeout,
        )
        target_widget = ctx.target_tool_widget
        if target_widget is not None:
            task.add_listener(target_widget.append_shell_output)
        if getattr(ctx, "session", None) and hasattr(ctx.session, "add_event"):
            task.add_listener(lambda chunk, tid=task_id: ctx.session.add_event({"type": "tool_shell_output", "text": chunk, "task_id": tid}))
        if not getattr(ctx, "is_subagent", False):
            ctx.attach_shell_widget(task_id, target_widget, is_background=False)
        callback = getattr(ctx.host, "on_background_shell_completed", None) if ctx.host else None
        progress_cb = getattr(ctx.host, "on_background_shell_progress", None) if ctx.host else None
        ctx.register_foreground_shell_task(task_id, task)
        read_task = task.start_reading(on_completed=callback, on_progress=progress_cb)

        start_time = time.monotonic()
        proc_task = asyncio.ensure_future(p.wait())
        bg_task = asyncio.ensure_future(task.background_event.wait())

        if wait_seconds is not None:
            sync_limit = float(wait_seconds)
            if hard_timeout is not None:
                sync_limit = min(sync_limit, float(hard_timeout))
        else:
            sync_limit = float(timeout)

        try:
            done, pending = await asyncio.wait(
                [proc_task, bg_task],
                timeout=sync_limit,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

            if not done:
                if wait_seconds is not None:
                    elapsed = max(0.1, round(time.monotonic() - start_time, 1))
                    if hard_timeout is not None and elapsed >= hard_timeout:
                        raise asyncio.TimeoutError()
                    _promote_task_to_background(task, ctx, target_widget)
                    raw_out = task.get_formatted_output().strip()
                    if raw_out:
                        truncated = truncate_output(
                            raw_out, max_chars=2000, tool_name="shell", save_log=False, from_end=True
                        ).strip()
                        plain_content = (
                            f"[task moved to background | id {task_id} | elapsed {elapsed}s | wait for notification]\n\n"
                            f"{truncated}"
                        )
                    else:
                        plain_content = (
                            f"[task moved to background | id {task_id} | elapsed {elapsed}s | wait for notification]"
                        )
                    return ToolResult(
                        status=ToolResultStatus.RUNNING,
                        content=plain_content,
                        task_id=task_id,
                        background_task_id=task_id,
                        log_path=task.log_path,
                    )
                raise asyncio.TimeoutError()

            if task.background_event.is_set() or getattr(task, "is_background", False):
                _promote_task_to_background(task, ctx, target_widget)
                elapsed = max(0.1, round(time.monotonic() - start_time, 1))
                raw_out = task.get_formatted_output().strip()
                if raw_out:
                    truncated = truncate_output(
                        raw_out, max_chars=2000, tool_name="shell", save_log=False, from_end=True
                    ).strip()
                    plain_content = (
                        f"[task backgrounded by user | id {task_id} | elapsed {elapsed}s | wait for notification]\n\n"
                        f"{truncated}"
                    )
                else:
                    plain_content = (
                        f"[task backgrounded by user | id {task_id} | elapsed {elapsed}s | no output yet (buffered) | wait for notification]"
                    )
                return ToolResult(
                    status=ToolResultStatus.RUNNING,
                    content=plain_content,
                    task_id=task_id,
                    background_task_id=task_id,
                    log_path=task.log_path,
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
            content_str = f"[exit {returncode}]\n{truncated}" if (returncode is not None and returncode != 0) else truncated
            return ToolResult.done(content=content_str, display=content_str, returncode=returncode)
        except asyncio.TimeoutError:
            try:
                await asyncio.shield(terminate_process(p))
            except Exception:
                pass
            await _cancel_read_task(read_task)
            raw_out = _truncate_output(task.get_formatted_output()).strip()
            partial_str = f"\n\n{raw_out}" if raw_out else ""
            effective_timeout = hard_timeout if (wait_seconds is not None and hard_timeout is not None) else timeout
            disp = f"ERR: timeout 'shell': timed out after {effective_timeout}s{partial_str}"
            return ToolResult.error("timeout", f"timed out after {effective_timeout}s{partial_str}", name="shell", display=disp)
        except asyncio.CancelledError:
            await _cancel_read_task(read_task)
            try:
                await asyncio.shield(terminate_process(p))
            except Exception:
                pass
            raise
        finally:
            ctx.cleanup_foreground_shell_task(task_id)
            if not getattr(task, "is_background", False):
                mgr = getattr(ctx, "task_manager", None)
                if mgr is not None and hasattr(mgr, "drop"):
                    try:
                        mgr.drop(task.task_id)
                    except Exception:
                        pass
                ctx.detach_shell_widget(task.task_id)

    async def _create_std_process(
        self,
        command: str,
        env: dict[str, str],
        cwd: Optional[str] = None,
        workspace_dir: Optional[str] = None,
        sandbox_enabled: bool = False,
        allow_workspace_writes: bool = True,
    ):
        return await spawn_shell_process(
            command=command,
            env=env,
            cwd=cwd,
            workspace_dir=workspace_dir,
            sandbox_enabled=sandbox_enabled,
            allow_workspace_writes=allow_workspace_writes,
            executable=shell_executable(),
            is_win=is_windows(),
            windows_spawner=self._create_windows_process,
        )

    async def _create_windows_process(self, command: str, env: dict[str, str], cwd: Optional[str] = None):
        return await spawn_windows_process(
            command=command,
            env=env,
            cwd=cwd,
            executable=shell_executable(),
        )

