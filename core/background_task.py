import asyncio
import os
import re

from core.platform_utils import terminate_process

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub('', text)


def process_carriage_returns(text: str) -> str:
    if not text:
        return ""
    lines = text.split("\n")
    processed = []
    for line in lines:
        if "\r" in line:
            parts = [p for p in line.split("\r") if p]
            line = parts[-1] if parts else ""
        processed.append(line)

    filtered = []
    spinner_chars = {"-", "\\", "|", "/", "—"}
    for line in processed:
        stripped = line.strip()
        if stripped in spinner_chars and filtered and filtered[-1].strip() in spinner_chars:
            filtered[-1] = line
        else:
            filtered.append(line)
    return "\n".join(filtered)


class BackgroundTask:
    """Manages background bash process with real-time line/chunk output reading and input sending"""
    def __init__(self, task_id: str, command: str, process, widget=None, master_fd: int = None, reader=None, transport=None, session_id: str = None):
        self.task_id = task_id
        self.command = command
        self.process = process
        self.output = []
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


    def get_formatted_output(self) -> str:
        """Returns full output with ANSI escape codes stripped and carriage returns collapsed"""
        if not hasattr(self, "_cached_len"):
            self._cached_len = -1
            self._cached_formatted = ""
        if len(self.output) != self._cached_len:
            raw = "".join(self.output)
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
                        text = chunk.decode("utf-8", errors="replace")
                    else:
                        chunk = await self.process.stdout.read(1024)
                        if not chunk:
                            break
                        text = chunk.decode("utf-8", errors="replace")

                    self.output.append(text)
                    if self.widget:
                        func = getattr(self.widget, "append_shell_output", getattr(self.widget, "append_bash_output", None))
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

                if self.is_background and not self.was_killed and on_completed_cb and getattr(app, "is_app_active", True):
                    try:
                        out_res = self.get_formatted_output()
                        if len(out_res) > 3000:
                            out_res = out_res[:3000] + "\n... [output truncated]"
                        out_res = out_res if out_res.strip() else "OK: executed (no output)"
                        on_completed_cb(self.task_id, self.command, out_res)
                    except Exception:
                        pass

        self.read_task = asyncio.create_task(_read())
        return self.read_task

    async def send_input(self, text: str) -> str:
        if not self.is_running:
            return f"ERR: task '{self.task_id}' not running"
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
                return f"ERR: task '{self.task_id}' stdin not writable"
        except Exception as e:
            return f"ERR: send input to {self.task_id}: {e}"

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


class BackgroundSubagent:
    """Manages background subagent"""
    def __init__(self, task_id: str, description: str, task: asyncio.Task, session_id: str = None):
        self.task_id = task_id
        self.command = f"Subagent: {description}"
        self.process = None
        self.output = []
        self._is_running_override = None
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

    def kill_sync(self):
        if self.async_task and not self.async_task.done():
            try:
                self.async_task.cancel()
            except Exception:
                pass
        self.is_running = False

    async def kill(self):
        if self.is_running and self.async_task:
            try:
                self.async_task.cancel()
            except Exception:
                pass
        self.is_running = False
        self.output.append("\n[Subagent task terminated by user]\n")
