import asyncio
import os
from typing import List, Optional


async def terminate_process(proc: asyncio.subprocess.Process, timeout: float = 3.0) -> None:
    """Safely terminate an asyncio subprocess, escalating to SIGKILL if necessary."""
    if proc is None or proc.returncode is not None:
        return

    try:
        proc.terminate()
    except ProcessLookupError:
        return

    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except (ProcessLookupError, asyncio.TimeoutError):
            pass


class BackgroundTask:
    """Manages background shell process execution and output accumulation."""

    def __init__(
        self,
        task_id: str,
        command: str,
        process: asyncio.subprocess.Process,
        read_task: asyncio.Task,
        session_id: Optional[str] = None,
        cwd: Optional[str] = None,
    ):
        self.task_id = task_id
        self.command = command
        self.process = process
        self.read_task = read_task
        self.session_id = session_id
        self.cwd = cwd or os.getcwd()
        self.output: List[str] = []
        self.is_running = True
        self.is_background = True
        self.was_killed = False

    def get_output_text(self, char_limit: Optional[int] = None) -> str:
        text = "".join(self.output)
        if char_limit is not None and len(text) > char_limit:
            return text[-char_limit:]
        return text

    def close_pty(self) -> None:
        """Close pseudo-terminal master fd if active."""
        if hasattr(self, "master_fd") and self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

    async def kill(self) -> None:
        self.was_killed = True
        self.is_running = False
        self.close_pty()
        if self.process:
            await terminate_process(self.process)
        if self.read_task and not self.read_task.done():
            self.read_task.cancel()
        self.output.append("\n[Task terminated by user]\n")


class BackgroundSubagent:
    """Manages background subagent execution tracking."""

    def __init__(self, task_id: str, description: str, task: asyncio.Task, session_id: Optional[str] = None):
        self.task_id = task_id
        self.command = f"Subagent: {description}"
        self.process = None
        self.output: List[str] = []
        self._is_running_override: Optional[bool] = None
        self.is_background = True
        self.async_task = task
        self.session_id = session_id

    @property
    def is_running(self) -> bool:
        if self._is_running_override is not None:
            return self._is_running_override
        if self.async_task and not self.async_task.done():
            return True
        return False

    @is_running.setter
    def is_running(self, val: bool) -> None:
        self._is_running_override = val

    def kill_sync(self) -> None:
        if self.async_task and not self.async_task.done():
            try:
                self.async_task.cancel()
            except Exception:
                pass
        self.is_running = False

    async def kill(self) -> None:
        if self.is_running and self.async_task:
            try:
                self.async_task.cancel()
            except Exception:
                pass
        self.is_running = False
        self.output.append("\n[Subagent task terminated by user]\n")
