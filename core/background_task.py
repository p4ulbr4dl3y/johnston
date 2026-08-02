import asyncio
import os
import re

from core.platform_utils import terminate_process

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub('', text)


def process_carriage_returns(text: str) -> str:
    if "\r" not in text:
        return text
    lines = text.split("\n")
    processed = []
    for line in lines:
        if "\r" in line:
            parts = [p for p in line.split("\r") if p]
            line = parts[-1] if parts else ""
        processed.append(line)
    return "\n".join(processed)


INTERACTIVE_PROMPT_REGEX = re.compile(
    r'(?:Press RETURN|\[y/N\]|\[Y/n\]|\(y/n\)|\(Y/N\)|[Ff]ile to patch|[Pp]assword:|[Pp]assphrase:|[Cc]onfirm\?|\[y/n/q\])',
)


class BackgroundTask:
    """Manages background bash process with real-time line/chunk output reading and input sending"""
    def __init__(self, task_id: str, command: str, process, widget=None, master_fd: int = None, reader=None, transport=None):
        self.task_id = task_id
        self.command = command
        self.process = process
        self.output = []
        self.is_running = True
        self.is_background = False
        self.prompt_notified = False
        self.was_killed = False
        self.read_task = None
        self.widget = widget
        self.master_fd = master_fd
        self.reader = reader
        self.transport = transport

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

    def start_reading(self, app, on_completed_cb, on_prompt_cb=None):
        prompt_callback = on_prompt_cb or getattr(app, "on_background_shell_prompt", None)

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
                        line = await self.process.stdout.readline()
                        if not line:
                            break
                        text = line.decode("utf-8", errors="replace")

                    self.output.append(text)
                    if self.widget and hasattr(self.widget, "append_bash_output"):
                        try:
                            if getattr(self.widget, "is_mounted", True):
                                self.widget.append_bash_output(strip_ansi(text))
                        except Exception:
                            pass

                    if self.is_background and not self.prompt_notified and prompt_callback and getattr(app, "is_app_active", True):
                        formatted = self.get_formatted_output()
                        tail = formatted[-500:]
                        if INTERACTIVE_PROMPT_REGEX.search(tail):
                            self.prompt_notified = True
                            try:
                                prompt_callback(self.task_id, self.command, tail)
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
                        out_res = out_res if out_res.strip() else "Command executed with no output."
                        on_completed_cb(self.task_id, self.command, out_res)
                    except Exception:
                        pass

        self.read_task = asyncio.create_task(_read())
        return self.read_task

    async def send_input(self, text: str) -> str:
        if not self.is_running:
            return f"Task {self.task_id} is not running."
        self.prompt_notified = False
        data = (text + "\n").encode("utf-8")
        try:
            if self.master_fd is not None:
                os.write(self.master_fd, data)
                return f"Input sent to task {self.task_id}."
            elif self.process and self.process.stdin:
                self.process.stdin.write(data)
                await self.process.stdin.drain()
                return f"Input sent to task {self.task_id}."
            else:
                return f"Task {self.task_id} stdin is not writable."
        except Exception as e:
            return f"Failed to send input to task {self.task_id}: {e}"

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
    def __init__(self, task_id: str, description: str, task: asyncio.Task):
        self.task_id = task_id
        self.command = f"Subagent: {description}"
        self.process = None
        self.output = []
        self.is_running = True
        self.is_background = True
        self.async_task = task

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
