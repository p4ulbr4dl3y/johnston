"""Shell task: a BaseTask backed by a live subprocess.

Self-contained: composes a subprocess + OutputBuffer directly, providing
real-time output, input and kill semantics for background shell processes.
"""

import asyncio
import os
import signal
from typing import Any, Optional

from core.domain.defaults.errors import format_tool_error
from core.infrastructure.platform.platform_utils import decode_output, terminate_process
from core.infrastructure.tasks.output import OutputBuffer, OutputLog, strip_ansi
from core.infrastructure.tasks.task import BaseTask, TaskStatus

_TASK_TERMINATED_BY_USER = "\n[Task terminated by user]\n"


class ShellTask(BaseTask):
    """Manages a background bash/pty subprocess with real-time output and input."""

    def __init__(
        self,
        task_id: str,
        command: str,
        process: Any = None,
        *,
        master_fd: Optional[int] = None,
        reader: Any = None,
        transport: Any = None,
        session_id: Optional[str] = None,
        widget: Any = None,
    ) -> None:
        super().__init__(task_id, kind="shell", command=command, status=TaskStatus.RUNNING)
        self.process = process
        self.master_fd = master_fd
        self.reader = reader
        self.transport = transport
        self.session_id = session_id
        self.widget = widget
        self.output = OutputBuffer()
        self.is_background = False
        self.was_killed = False
        self.read_task: Optional[asyncio.Task] = None
        self.background_event = asyncio.Event()
        self._done: Optional[asyncio.Future] = None
        # File log for background tasks (full output, no memory cap).
        self.log_path: Optional[str] = None
        self._log: Optional[OutputLog] = None

    def open_log(self) -> Optional[str]:
        """Enable full-output file logging (used for background tasks).

        Streams every decoded chunk to a unique log under LOGS_DIR, bypassing the
        in-memory OutputBuffer cap. Returns the path, or None if logging was
        skipped (already open) or the file could not be created.

        On first open any output already buffered in ``self.output`` is written
        to the log so a latently-opened log (e.g. on timeout->background
        conversion) is not missing the leading output.
        """
        if self._log is not None:
            return self.log_path
        self._log = OutputLog.create(self.task_id)
        if self._log.opened:
            self.log_path = self._log.path
            backfill = "".join(self.output.history)
            if backfill:
                self._log.append(backfill)
            # Readers may inspect the log before the worker drains; flush now so
            # the backfilled output is visible synchronously on disk.
            self._log.flush_now()
            return self.log_path
        self._log = None
        return None

    def close_log(self) -> None:
        if self._log is not None:
            self._log.close()
            self._log = None

    def _done_future(self) -> asyncio.Future:
        if self._done is None:
            self._done = asyncio.get_running_loop().create_future()
        return self._done

    def __repr__(self) -> str:
        return f"ShellTask(id={self.id!r}, status={self._status.value})"

    # -- Task API ------------------------------------------------------------

    def move_to_background(self) -> None:
        self.is_background = True
        self.background_event.set()
        self.open_log()

    def get_formatted_output(self) -> str:
        """Return the fully formatted output (truncation marker + stripped text)."""
        return self.output.formatted()

    def close_pty(self) -> None:
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                pass
            self.transport = None
            self.master_fd = None
        elif self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except Exception:
                pass
            self.master_fd = None

    # -- start --------------------------------------------------------------

    def start_reading(self, on_chunk=None, on_completed=None) -> asyncio.Task:
        """Begin reading the process output in the background.

        ``on_chunk`` (callable, optional) receives each decoded text chunk.
        ``on_completed`` (callable, optional) is fired with (task_id, command,
        formatted_output) when the process exits.
        """

        def _append_chunk(text: str) -> None:
            self.output.append(text)
            if self._log is not None:
                self._log.append(text)
            if self.widget is not None:
                func = getattr(
                    self.widget, "append_shell_output", getattr(self.widget, "append_bash_output", None)
                )
                if func and getattr(self.widget, "is_mounted", True):
                    try:
                        func(strip_ansi(text))
                    except Exception:
                        pass
            if on_chunk is not None:
                try:
                    on_chunk(text)
                except Exception:
                    pass

        async def _read():
            try:
                while True:
                    chunk_data = None
                    if self.reader is not None:
                        try:
                            chunk_data = await self.reader.read(1024)
                        except (OSError, Exception):
                            break
                    elif self.process is not None:
                        try:
                            chunk_data = await self.process.stdout.read(1024)
                        except (OSError, Exception):
                            break
                    else:
                        break
                    if not chunk_data:
                        break
                    _append_chunk(decode_output(chunk_data))
            except Exception:
                pass
            finally:
                self.close_pty()
                self.close_log()
                self._mark_terminated()

                if self.process is not None:
                    try:
                        if self.process.returncode is None:
                            try:
                                await asyncio.wait_for(asyncio.shield(self.process.wait()), timeout=0.1)
                            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                                pass
                    except Exception:
                        pass

                if on_completed is not None and not self.was_killed and self.is_background:
                    try:
                        out = self.output.formatted()
                        on_completed(self.task_id, self.command, out or "(no output)")
                    except Exception:
                        pass

        self.read_task = asyncio.create_task(_read())
        return self.read_task

    def _mark_terminated(self, status: TaskStatus = TaskStatus.COMPLETED) -> None:
        if self._done is not None and self._done.done():
            return
        self.status = status
        self._done_future().set_result(True)

    # -- BaseTask API -------------------------------------------------------

    async def read(self) -> str:
        return self.output.formatted()

    async def tail(self, max_chars: int = 4000) -> str:
        return self.output.formatted(max_chars=max_chars)

    async def wait(self) -> None:
        await self._done_future()

    # -- input --------------------------------------------------------------

    async def send_input(self, text: str) -> str:
        if not self.is_running:
            return format_tool_error("task", f"{self.task_id} not running")
        data = (text + "\n").encode("utf-8")
        try:
            if self.master_fd is not None:
                await asyncio.to_thread(os.write, self.master_fd, data)
                return f"OK: input sent to {self.task_id}"
            if self.process is not None and self.process.stdin is not None:
                await asyncio.to_thread(self.process.stdin.write, data)
                await self.process.stdin.drain()
                return f"OK: input sent to {self.task_id}"
            return format_tool_error("task", f"{self.task_id} stdin not writable")
        except Exception as exc:
            return format_tool_error("task", f"send input to {self.task_id}: {exc}")

    # -- kill ---------------------------------------------------------------

    async def kill(self) -> None:
        self.was_killed = True
        self.is_background = False
        self.close_pty()
        self.close_log()
        if self.process is not None:
            await terminate_process(self.process)
        if self.read_task is not None and not self.read_task.done():
            self.read_task.cancel()
        self.output.append(_TASK_TERMINATED_BY_USER)
        self._mark_terminated(TaskStatus.KILLED)

    def kill_sync(self) -> None:
        """Synchronous kill used by exit paths that run outside the event loop."""
        self.was_killed = True
        self.is_background = False
        self.close_pty()
        self.close_log()
        if self.process is not None:
            try:
                pid = getattr(self.process, "pid", None)
                if isinstance(pid, int) and pid > 0:
                    os.killpg(pid, signal.SIGKILL)
            except Exception:
                pass
            try:
                self.process.kill()
            except Exception:
                pass
        if self.read_task is not None and not self.read_task.done():
            self.read_task.cancel()
        self.output.append("\n[Task terminated]\n")
        self._mark_terminated(TaskStatus.KILLED)
