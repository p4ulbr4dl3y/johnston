"""TaskManager: pure in-memory aggregate of live tasks.

Holds no subprocess/session logic itself; it just registers BaseTask instances
and answers queries for the UI/footer.
"""

import asyncio
from typing import Dict, Optional

from core.infrastructure.tasks.task import BaseTask, TaskStatus

MAX_COMPLETED_TASKS = 50


class TaskManager:
    """Registry of live tasks."""

    def __init__(self, max_completed: int = MAX_COMPLETED_TASKS) -> None:
        self._tasks: Dict[str, BaseTask] = {}
        self._max_completed = max_completed

    # -- registration -------------------------------------------------------

    def register(self, task: BaseTask) -> BaseTask:
        self._tasks[task.id] = task
        self._schedule_task_cleanup(task)
        self.prune_completed()
        return task

    def drop(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)

    def prune_completed(self, max_retained: Optional[int] = None) -> None:
        """Prune finished tasks when count of completed tasks exceeds limit."""
        limit = self._max_completed if max_retained is None else max_retained
        completed = [
            t
            for t in self._tasks.values()
            if not getattr(t, "is_running", False)
            or getattr(t, "status", None)
            in (
                TaskStatus.COMPLETED,
                TaskStatus.ERROR,
                TaskStatus.KILLED,
                TaskStatus.TIMEOUT,
                "completed",
                "error",
                "killed",
                "timeout",
            )
        ]
        if len(completed) > limit:
            completed.sort(
                key=lambda t: (
                    getattr(t, "completed_at", None) or getattr(t, "created_at", 0.0) or 0.0
                )
            )
            for t in completed[: len(completed) - limit]:
                tid = getattr(t, "id", None) or getattr(t, "task_id", None)
                if tid:
                    self.drop(tid)

    def _schedule_task_cleanup(self, task: BaseTask) -> None:
        if not hasattr(task, "wait") or not callable(task.wait):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _watch() -> None:
            try:
                await task.wait()
            except Exception:
                pass
            self.prune_completed()

        try:
            loop.create_task(_watch())
        except Exception:
            pass

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
