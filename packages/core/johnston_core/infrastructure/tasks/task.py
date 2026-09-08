"""Abstract task contract for background tasks managed by TaskManager.

Defines the base abstraction for concrete task implementations (such as
ShellTask).
"""

import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

# Literal kind strings a background task may carry.
TASK_KINDS = ("shell", "subagent")


class TaskStatus(str, Enum):
    """Lifecycle status for a task."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    KILLED = "killed"
    TIMEOUT = "timeout"

    @property
    def is_running(self) -> bool:
        return self == TaskStatus.RUNNING

    @property
    def is_active(self) -> bool:
        return self in (TaskStatus.QUEUED, TaskStatus.RUNNING)


class BaseTask(ABC):
    """Abstract contract for every task managed by TaskManager.

    Concrete subclasses (ShellTask) provide execution, buffered output and kill
    semantics. All methods are safe to call concurrently; the implementations
    are responsible for their own locking.
    """

    def __init__(
        self,
        task_id: str,
        kind: str = "shell",
        command: str = "",
        status: TaskStatus = TaskStatus.QUEUED,
        created_at: Optional[float] = None,
    ) -> None:
        if kind not in TASK_KINDS:
            raise ValueError(f"unknown task kind: {kind!r}")
        self.id = task_id
        self.task_id = task_id
        self.kind = kind
        self.command = command
        self._status = status
        self.created_at = created_at if created_at is not None else time.time()
        self.completed_at: Optional[float] = None
        self.exit_code: Optional[int] = None

    # -- identity ----------------------------------------------------------

    @abstractmethod
    def __repr__(self) -> str:
        ...

    # -- status ------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """True while the task status is RUNNING."""
        return self.status == TaskStatus.RUNNING

    @property
    def is_active(self) -> bool:
        """True while the task status is QUEUED or RUNNING."""
        return self.status in (TaskStatus.QUEUED, TaskStatus.RUNNING)

    @property
    def status(self) -> TaskStatus:
        return self._status

    @status.setter
    def status(self, value: TaskStatus) -> None:
        self._status = value

    def _process_alive(self) -> bool:
        proc = getattr(self, "process", None)
        if proc is None:
            return False
        try:
            rc = getattr(proc, "returncode", None)
            if rc is None:
                return True
            if isinstance(rc, int):
                return False
            return True
        except Exception:
            return False

    # -- io -----------------------------------------------------------------

    @abstractmethod
    async def read(self) -> str:
        """Return the full (formatted) output accumulated so far."""

    @abstractmethod
    async def tail(self, max_chars: int = 4000) -> str:
        """Return the trailing portion of the output, at most max_chars."""

    @abstractmethod
    async def kill(self) -> None:
        """Terminate the task and transition it to a terminal status."""

    @abstractmethod
    async def wait(self) -> None:
        """Block until the task reaches a terminal status."""
