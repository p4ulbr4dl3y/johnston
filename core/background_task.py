import asyncio


class BackgroundTask:
    """Управление фоновым bash-процессом с построчным чтением вывода в реальном времени"""
    def __init__(self, task_id: str, command: str, process, widget=None):
        self.task_id = task_id
        self.command = command
        self.process = process
        self.output = []
        self.is_running = True
        self.is_background = False
        self.read_task = None
        self.widget = widget

    def start_reading(self, app, on_completed_cb):
        async def _read():
            try:
                while True:
                    line = await self.process.stdout.readline()
                    if not line:
                        break
                    line_str = line.decode("utf-8", errors="replace")
                    self.output.append(line_str)
                    if self.widget and hasattr(self.widget, "append_bash_output"):
                        try:
                            if getattr(self.widget, "is_mounted", True):
                                self.widget.append_bash_output(line_str)
                        except Exception:
                            pass
            except Exception:
                pass
            finally:
                self.is_running = False
                if self.process:
                    try:
                        await self.process.wait()
                    except Exception:
                        pass

                if self.is_background and on_completed_cb and getattr(app, "is_running", True):
                    try:
                        out_res = "".join(self.output)
                        if len(out_res) > 3000:
                            out_res = out_res[:3000] + "\n... [output truncated]"
                        out_res = out_res if out_res.strip() else "Command executed with no output."
                        on_completed_cb(self.task_id, self.command, out_res)
                    except Exception:
                        pass

        self.read_task = asyncio.create_task(_read())
        return self.read_task

    async def kill(self):
        self.is_running = False
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=1.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
        if self.read_task and not self.read_task.done():
            self.read_task.cancel()
        self.output.append("\n[Task terminated by user]\n")


class BackgroundSubagent:
    """Управление фоновым субагентом"""
    def __init__(self, task_id: str, description: str, task: asyncio.Task):
        self.task_id = task_id
        self.command = f"Subagent: {description}"
        self.process = None
        self.output = []
        self.is_running = True
        self.is_background = True
        self.async_task = task

    async def kill(self):
        if self.is_running and self.async_task:
            try:
                self.async_task.cancel()
            except Exception:
                pass
        self.is_running = False
        self.output.append("\n[Subagent task terminated by user]\n")
