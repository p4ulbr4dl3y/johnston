import asyncio

class BackgroundTask:
    """Управление фоновым bash-процессом с построчным чтением вывода в реальном времени"""
    def __init__(self, task_id: str, command: str, process):
        self.task_id = task_id
        self.command = command
        self.process = process
        self.output = []
        self.is_running = True
        self.is_background = False

    def start_reading(self, app, on_completed_cb):
        async def _read():
            try:
                while True:
                    line = await self.process.stdout.readline()
                    if not line:
                        break
                    self.output.append(line.decode("utf-8", errors="replace"))
            except Exception:
                pass
            finally:
                self.is_running = False
                if self.process:
                    try:
                        await self.process.wait()
                    except Exception:
                        pass

                if self.is_background and on_completed_cb:
                    # Формируем итоговый результат
                    out_res = "".join(self.output)
                    if len(out_res) > 3000:
                        out_res = out_res[:3000] + "\n... [output truncated]"
                    out_res = out_res if out_res.strip() else "Command executed with no output."
                    on_completed_cb(self.task_id, self.command, out_res)

        asyncio.create_task(_read())

    async def kill(self):
        if self.is_running and self.process:
            try:
                self.process.terminate()
                await self.process.wait()
            except Exception:
                pass
        self.is_running = False
        self.output.append("\n[Task terminated by user]\n")
