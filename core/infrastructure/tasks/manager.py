"""TaskManager: pure in-memory aggregate of live tasks.

Holds no subprocess/session logic itself; it just registers BaseTask instances
and answers queries for the UI/footer.
"""

import asyncio
from typing import Any, Dict

from core.infrastructure.tasks.task import BaseTask


class TaskManager:
    """Registry of live tasks."""

    def __init__(self, app: Any = None) -> None:
        self._tasks: Dict[str, BaseTask] = {}

    # -- registration -------------------------------------------------------

    def register(self, task: BaseTask) -> BaseTask:
        self._tasks[task.id] = task
        return task

    def drop(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)

    # -- lifecycle ----------------------------------------------------------

    async def kill_all(self) -> None:
        for task in list(self._tasks.values()):
            try:
                await task.kill()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    def __iter__(self):
        return iter(list(self._tasks.values()))
