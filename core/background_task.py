import asyncio
import logging
import os
from collections import deque

from core.platform_utils import decode_output, terminate_process
from core.tasks.output import _OUTPUT_BYTE_LIMIT, _OUTPUT_TRUNCATED_MARKER, process_carriage_returns, strip_ansi
from tools.base import format_tool_error

logger = logging.getLogger(__name__)


class BackgroundTask:
    """Manages background bash process with real-time line/chunk output reading and input sending"""

    def __init__(
        self,
        task_id: str,
        command: str,
        process,
        widget=None,
        master_fd: int = None,
        reader=None,
        transport=None,
        session_id: str = None,
        kind: str = "shell",
    ):
        self.task_id = task_id
        self.kind = kind
        self.command = command
        self.process = process
        self.output = deque()
        self._output_size = 0
        self._output_truncated = False
        self.is_running = True
        self.is_background = False
        self.was_killed = False
        self.read_task = None
        self.widget = widget
        self.master_fd = master_fd
        self.reader = reader
        self.transport = transport
        self.session_id = session_id
        self.background_event = asyncio.Event()

    def move_to_background(self):
        self.is_background = True
        self.background_event.set()

    def close_pty(self):
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

    def _append_output(self, text: str) -> None:
        """Append a chunk, dropping old chunks from the front past the cap."""
        self.output.append(text)
        self._output_size += len(text)
        if self._output_size > _OUTPUT_BYTE_LIMIT:
            self._output_truncated = True
            while self.output and self._output_size > _OUTPUT_BYTE_LIMIT // 2:
                self._output_size -= len(self.output.popleft())

    def get_formatted_output(self) -> str:
        """Returns full output with ANSI escape codes stripped and carriage returns collapsed"""
        if not hasattr(self, "_cached_len"):
            self._cached_len = -1
            self._cached_formatted = ""
        if len(self.output) != self._cached_len:
            raw = ""
            if self._output_truncated:
                raw += _OUTPUT_TRUNCATED_MARKER
            raw += "".join(self.output)
            self._cached_formatted = process_carriage_returns(strip_ansi(raw))
            self._cached_len = len(self.output)
        return self._cached_formatted

    def start_reading(self, app, on_completed_cb):
        async def _read():
            try:
                while True:
                    if self.reader:
                        try:
                            chunk = await self.reader.read(1024)
                        except (OSError, Exception):
                            break
                        if not chunk:
                            break
                        text = decode_output(chunk)
                    else:
                        chunk = await self.process.stdout.read(1024)
                        if not chunk:
                            break
                        text = decode_output(chunk)

                    self._append_output(text)
                    if self.widget:
                        func = getattr(
                            self.widget, "append_shell_output", getattr(self.widget, "append_bash_output", None)
                        )
                        if func:
                            try:
                                if getattr(self.widget, "is_mounted", True):
                                    func(strip_ansi(text))
                            except Exception:
                                pass
            except Exception:
                pass
            finally:
                self.is_running = False
                self.close_pty()

                if self.process:
                    try:
                        if self.process.returncode is None:
                            try:
                                await asyncio.wait_for(self.process.wait(), timeout=0.1)
                            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                                pass
                    except Exception:
                        pass

                if (
                    self.is_background
                    and not self.was_killed
                    and on_completed_cb
                    and getattr(app, "is_app_active", True)
                ):
                    try:
                        from tools.base import truncate_output

                        out_res = self.get_formatted_output()
                        if out_res.strip():
                            out_res = truncate_output(
                                out_res,
                                max_chars=4000,
                                hint="Pipe output to grep/head/tail if complete log is needed.",
                                tool_name="shell",
                                tool_id=self.task_id,
                                from_end=True,
                            )
                        else:
                            out_res = "(no output)"
                        on_completed_cb(self.task_id, self.command, out_res)
                    except Exception:
                        logger.warning(
                            "Background task on_completed callback failed for task %s", self.task_id, exc_info=True
                        )

        self.read_task = asyncio.create_task(_read())
        return self.read_task

    async def send_input(self, text: str) -> str:
        if not self.is_running:
            return format_tool_error("task", f"{self.task_id} not running")
        data = (text + "\n").encode("utf-8")
        try:
            if self.master_fd is not None:
                os.write(self.master_fd, data)
                return f"OK: input sent to {self.task_id}"
            elif self.process and self.process.stdin:
                self.process.stdin.write(data)
                await self.process.stdin.drain()
                return f"OK: input sent to {self.task_id}"
            else:
                return format_tool_error("task", f"{self.task_id} stdin not writable")
        except Exception as e:
            return format_tool_error("task", f"send input to {self.task_id}: {e}")

    def kill_sync(self):
        self.was_killed = True
        self.is_running = False
        self.close_pty()
        if self.process:
            try:
                pid = getattr(self.process, "pid", None)
                if isinstance(pid, int) and pid > 0:
                    try:
                        import signal

                        os.killpg(pid, signal.SIGKILL)
                    except Exception:
                        pass
                try:
                    self.process.kill()
                except Exception:
                    pass
            except Exception:
                pass
        if self.read_task and not self.read_task.done():
            self.read_task.cancel()
        self.output.append("\n[Task terminated]\n")

    async def kill(self):
        self.was_killed = True
        self.is_running = False
        self.close_pty()
        if self.process:
            await terminate_process(self.process)
        if self.read_task and not self.read_task.done():
            self.read_task.cancel()
        self.output.append("\n[Task terminated by user]\n")


def kill_all_background_tasks(tasks) -> None:
    """Kills every background shell task in the list (used on app exit and /new)."""
    for task in tasks:
        try:
            if hasattr(task, "kill_sync"):
                task.kill_sync()
            elif hasattr(task, "kill") and asyncio.iscoroutinefunction(task.kill):
                asyncio.create_task(task.kill())
            elif hasattr(task, "process") and task.process:
                try:
                    task.process.terminate()
                except Exception:
                    pass
            if hasattr(task, "read_task") and task.read_task:
                task.read_task.cancel()
        except Exception:
            pass
