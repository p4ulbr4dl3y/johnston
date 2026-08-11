import asyncio
import itertools
import re
import time
from collections import deque
from typing import Any, Dict

from core.background_task import BackgroundTask, process_carriage_returns, strip_ansi
from core.platform_utils import (
    decode_output,
    is_windows,
    shell_env,
    shell_executable,
    shell_subprocess_kwargs,
    terminate_process,
)
from tools.base import BaseTool, format_tool_error, tail_output, truncate_output

SLEEP_CHAIN_REGEX = re.compile(r"^sleep\s+([0-9]+(?:\.[0-9]+)?)\s*(?:(?:&&|;)\s*(.*))?$", re.DOTALL)
_TASK_ID_COUNTER = itertools.count(1)


def _new_task_id() -> str:
    return f"shell_{time.time_ns()}_{next(_TASK_ID_COUNTER)}"


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
    description = (
        "Run a terminal command. Moves to background past timeout (default 120s). Destructive commands confirm."
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
                        "description": "Terminal command to run (resolved relative to current working directory, cwd)",
                    },
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 120, max 600)"},
                    "background": {"type": "boolean", "description": "Run command in background immediately"},
                },
                "required": ["command"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> str:
        from tools.registry import normalize_tool_args

        args = normalize_tool_args("shell", args)
        ctx = self._ensure_context(ctx)
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
                return format_tool_error("reject", detail=f"sleep {sec}s exceeds timeout {timeout}s")
            await asyncio.sleep(sec)
            if not remainder:
                return f"slept {sec}s"
            cmd = remainder

        skip_confirm = bool(args.get("skip_confirm", False))
        from core.shell_guard import analyze_shell_command

        is_safe, reason = analyze_shell_command(cmd)

        from core.permission_manager import PermissionManager

        pm = PermissionManager.get_instance()
        effective_perms = pm.get_effective_permissions()
        sg_enabled = effective_perms.get("shell_guard", {}).get("enabled", True)
        session_override = pm.session_overrides.get("shell") or pm.session_overrides.get("shell_guard")

        if sg_enabled and not is_safe and not skip_confirm and session_override != "allow":
            from tools.registry import check_and_confirm_permission

            try:
                # shell_guard already evaluated the command as unsafe; reuse the unified
                # permission prompt helper (handles app prompt, session overrides, headless).
                err = await check_and_confirm_permission(
                    "shell", "shell", {"command": cmd}, ctx, action="ask", action_reason=reason
                )
            except Exception as e:
                return format_tool_error("permission", detail=str(e), name="shell")
            if err:
                return err

        env = shell_env()
        proc_cwd = ctx.cwd if isinstance(getattr(ctx, "cwd", None), str) else None
        p = await self._create_std_process(cmd, env, cwd=proc_cwd)

        run_in_bg = bool(args.get("run_in_background", False))

        # Synchronous execution mode for subagents (no background task)
        if ctx.is_subagent:
            if run_in_bg:
                await terminate_process(p)
                return format_tool_error("background", name="shell")

            output_chunks = deque()
            output_size = 0
            output_truncated = False
            _SUBAGENT_OUTPUT_LIMIT = 2 * 1024 * 1024  # 2 MB cap (mirrors web_fetch)

            def _flush_raw() -> str:
                raw_all = "".join(output_chunks)
                if output_truncated:
                    raw_all = "[Output truncated: showing recent output]\n" + raw_all
                return raw_all

            async def _read_stream(stream):
                nonlocal output_size, output_truncated
                if not stream:
                    return
                while True:
                    try:
                        chunk = await stream.read(1024)
                        if not chunk:
                            break
                        text = decode_output(chunk)
                        output_chunks.append(text)
                        output_size += len(text)
                        if output_size > _SUBAGENT_OUTPUT_LIMIT:
                            output_truncated = True
                            # Drop old chunks from the front, keeping the tail.
                            while output_chunks and output_size > _SUBAGENT_OUTPUT_LIMIT // 2:
                                output_size -= len(output_chunks.popleft())
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
                res = process_carriage_returns(strip_ansi(_flush_raw()))
                if not res.strip():
                    return "(no output)"
                return _truncate_output(res)
            except asyncio.TimeoutError:
                await terminate_process(p)
                if read_task:
                    try:
                        await asyncio.wait_for(read_task, timeout=1.0)
                    except Exception:
                        pass
                raw_out = process_carriage_returns(strip_ansi(_flush_raw()))
                partial_str = f"\n\nPartial Output:\n{raw_out.strip()}" if raw_out.strip() else ""
                return format_tool_error("timeout", f"timed out after {timeout}s{partial_str}", name="shell")
            except asyncio.CancelledError:
                await terminate_process(p)
                raise

        task_id = _new_task_id()
        target_widget = getattr(ctx.app, "current_tool_widget", None) if ctx.app else None
        curr_sid = getattr(ctx.app, "current_session_id", None) if ctx.app else None
        task = BackgroundTask(
            task_id,
            cmd,
            p,
            widget=target_widget,
            session_id=curr_sid,
        )
        callback = getattr(ctx.app, "on_background_shell_completed", None) if ctx.app else None

        if run_in_bg:
            task.is_background = True
            ctx.add_background_task(task)
            task.start_reading(ctx.app, callback)

            return (
                f"[Background Task ID: {task_id}] running: '{cmd}'. "
                f"manage_shell(send_input/kill, task_id='{task_id}') to respond/abort. End turn."
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

                raw_out = task.get_formatted_output()
                if raw_out.strip():
                    recent_output_str = f"\n\nRecent Output:\n{tail_output(raw_out, 2000)}"
                else:
                    recent_output_str = "\n\nRecent Output: (No output yet)"
                return (
                    f"[Background Task ID: {task_id}] running: '{cmd}'.{recent_output_str}\n"
                    f"manage_shell(send_input/kill, task_id='{task_id}') to respond/abort. End turn."
                )

            if task.read_task:
                try:
                    await asyncio.wait_for(task.read_task, timeout=2.0)
                except asyncio.TimeoutError:
                    pass
            task.close_pty()
            res = task.get_formatted_output()
            if not res.strip():
                return "(no output)"
            return _truncate_output(res)
        except asyncio.TimeoutError:
            task.is_background = True

            raw_out = task.get_formatted_output()
            if raw_out.strip():
                recent_output_str = f"\n\nRecent Output:\n{tail_output(raw_out, 2000)}"
            else:
                recent_output_str = "\n\nRecent Output: (No output yet)"
            return (
                f"[Background Task ID: {task_id}] running: '{cmd}'.{recent_output_str}\n"
                f"manage_shell(send_input/kill, task_id='{task_id}') to respond/abort. End turn."
            )
        except asyncio.CancelledError:
            if "task" in locals() and task:
                task.kill_sync()
                task.close_pty()
            elif "p" in locals() and p:
                try:
                    p.kill()
                except Exception:
                    pass
            raise
        finally:
            if "task" in locals() and task and not getattr(task, "is_background", False):
                if ctx.app and hasattr(ctx.app, "background_tasks") and task in ctx.app.background_tasks:
                    ctx.app.background_tasks.remove(task)

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
