"""TaskManager: pure in-memory aggregate of live tasks.

Holds no subprocess/session logic itself; it just registers BaseTask instances
and answers queries for the UI/footer. It accepts (but does not require)
references to app.background_tasks and app.sm so older code paths can be
bridged later without changing this module's interface.
"""

from typing import Any, Dict, List, Optional

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
        snapshots = [
            task.snapshot()
            for task in self._tasks.values()
            if getattr(task, "kind", "") != "session"
        ]
        return snapshots

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

    async def find(self, identifier: str) -> Optional[BaseTask]:
        """Locate a task by exact id, or by its description/command text."""
        if not identifier:
            return None
        clean = identifier.strip("\"' `")
        for task in self._tasks.values():
            if task.id == identifier or task.id == clean:
                return task
        for task in self._tasks.values():
            desc = getattr(task, "description", None) or getattr(task, "command", "")
            if not desc:
                continue
            if desc.strip("\"' `") == clean or clean in desc or desc in clean:
                return task
        return None

    # -- lifecycle ----------------------------------------------------------

    async def kill_all(self) -> None:
        for task in list(self._tasks.values()):
            try:
                await task.kill()
            except Exception:
                pass

    def __iter__(self):
        return iter(list(self._tasks.values()))
