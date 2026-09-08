"""Low-level OS process spawning utilities."""

import asyncio
from typing import Callable, Optional

from core.infrastructure.platform.platform_utils import (
    is_windows,
    shell_executable,
    shell_subprocess_kwargs,
)


async def spawn_windows_process(
    command: str,
    env: dict[str, str],
    cwd: Optional[str] = None,
    executable: Optional[str] = None,
) -> asyncio.subprocess.Process:
    """Spawn a Windows subprocess using PowerShell or cmd.exe depending on configuration."""
    shell = executable or shell_executable()
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
            stdin=asyncio.subprocess.DEVNULL,
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
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=cwd,
            **shell_subprocess_kwargs(),
        )
    return await asyncio.create_subprocess_shell(
        command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
        cwd=cwd,
        **shell_subprocess_kwargs(),
    )


async def spawn_shell_process(
    command: str,
    env: dict[str, str],
    cwd: Optional[str] = None,
    workspace_dir: Optional[str] = None,
    sandbox_enabled: bool = False,
    allow_workspace_writes: bool = True,
    executable: Optional[str] = None,
    is_win: Optional[bool] = None,
    windows_spawner: Optional[Callable] = None,
) -> asyncio.subprocess.Process:
    """Spawn a shell process, with optional sandboxing or Windows platform handling."""
    if sandbox_enabled:
        from core.infrastructure.platform.sandbox import build_sandboxed_command

        exe, args, is_sandboxed = build_sandboxed_command(
            command,
            cwd=cwd,
            workspace_dir=workspace_dir,
            allow_workspace_writes=allow_workspace_writes,
        )
        if is_sandboxed:
            return await asyncio.create_subprocess_exec(
                exe,
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=cwd,
                **shell_subprocess_kwargs(),
            )

    win = is_windows() if is_win is None else is_win
    if win:
        if windows_spawner is not None:
            return await windows_spawner(command, env, cwd=cwd)
        return await spawn_windows_process(command, env, cwd=cwd, executable=executable)

    shell = executable or shell_executable()
    return await asyncio.create_subprocess_shell(
        command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
        cwd=cwd,
        executable=shell,
        **shell_subprocess_kwargs(),
    )
