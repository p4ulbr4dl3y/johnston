"""TaskManager: pure in-memory aggregate of live tasks.

Holds no subprocess/session logic itself; it just registers BaseTask instances
and answers queries for the UI/footer.
"""

import asyncio
from typing import Any, Dict, List

from core.tasks.task import BaseTask, TaskSnapshot


class TaskManager:
    """Registry of live tasks with snapshot/query helpers."""

    def __init__(self, app: Any = None) -> None:
        self.app = app
        self._tasks: Dict[str, BaseTask] = {}
        self._snapshots: Dict[str, TaskSnapshot] = {}

    # -- registration -------------------------------------------------------

    def register(self, task: BaseTask) -> BaseTask:
        self._tasks[task.id] = task
        return task

    def drop(self, task_id: str) -> None:
        task = self._tasks.pop(task_id, None)
        if task is not None:
            self._snapshots.pop(task_id, None)

    # -- query --------------------------------------------------------------

    def list(self) -> List[TaskSnapshot]:
        return [task.snapshot() for task in self._tasks.values()]

    def by_session(self, session_id: str) -> List[BaseTask]:
        """Filter tasks by the session they back (shell/subagent session_id)."""
        result = []
        for task in self._tasks.values():
            sid = getattr(task, "session_id", None) or getattr(
                getattr(task, "session", None), "id", None
            )
            if sid == session_id:
                result.append(task)
        return result

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
