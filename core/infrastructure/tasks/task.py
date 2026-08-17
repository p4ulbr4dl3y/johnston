"""Abstract task contract for the unified task-core module.

Defines the base abstraction every concrete task implementation (shell,
subagent) implements, plus the snapshot type passed to the UI layer to avoid
races on live objects.
"""

import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

# Literal kind strings a task may carry ("shell" or "subagent").
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

    # -- identity ----------------------------------------------------------

    @abstractmethod
    def __repr__(self) -> str:
        ...

    # -- status ------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """True while the task status is running OR the backing process is alive.

        The process check keeps tasks with a replaced/dead status (e.g. a timed
        out task moved to background) responsive to manage_shell/ctrl+b as long
        as their subprocess still lives.
        """
        return self._status.is_running or self._process_alive()

    @property
    def status(self) -> TaskStatus:
        if self._status.is_running or self._process_alive():
            return TaskStatus.RUNNING
        return self._status

    @status.setter
    def status(self, value: TaskStatus) -> None:
        self._status = value

    def _process_alive(self) -> bool:
        proc = self.process
        if proc is None:
            return False
        return getattr(proc, "returncode", None) is None

    # -- io -----------------------------------------------------------------

    @abstractmethod
    async def read(self) -> str:
        """Return the full (formatted) output accumulated so far."""

    @abstractmethod
    async def tail(self, max_chars: int = 4000) -> str:
        """Return the trailing portion of the output, at most max_chars."""

    @abstractmethod
    async def send_input(self, text: str) -> str:
        """Send a line of input to the task.

        Shell tasks write to their pty/stdin.
        """

    @abstractmethod
    async def kill(self) -> None:
        """Terminate the task and transition it to a terminal status."""

    @abstractmethod
    async def wait(self) -> None:
        """Block until the task reaches a terminal status."""
