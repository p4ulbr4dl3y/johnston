"""Abstract task contract for the unified task-core module.

Defines the base abstraction every concrete task implementation (shell,
subagent) implements, plus the snapshot type passed to the UI layer to avoid
races on live objects.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional


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


class TaskIDKind(str, Enum):
    """Kinds of task identifiers a BaseTask may carry.

    Tasks back either a background shell process (kind="shell") or an
    AgentSession (kind="subagent"). The kind is used to route manager
    operations (e.g. shell lookup by id vs. session lookup).
    """

    SHELL = "shell"
    SUBAGENT = "subagent"


# Backwards-friendly literal for task "kind" strings.
TASK_KINDS = ("shell", "subagent")


@dataclass
class TaskSnapshot:
    """Immutable view of a task for UI layers.

    Deliberately carries only primitives so the UI never touches a live task
    object (avoiding race conditions when tasks complete/kill concurrently).
    """

    id: str
    kind: str
    status_str: str
    command: str
    is_running: bool


class BaseTask(ABC):
    """Abstract contract for every task managed by TaskManager.

    Concrete subclasses (ShellTask, SubagentTask) provide execution, buffered
    output and kill semantics. All methods are safe to call concurrently; the
    implementations are responsible for their own locking.
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
        self.task_id = task_id  # alias for BackgroundTask parity
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
    def status(self) -> TaskStatus:
        return self._status

    @status.setter
    def status(self, value: TaskStatus) -> None:
        self._status = value

    @property
    def is_running(self) -> bool:
        return self._status.is_running

    def snapshot(self) -> TaskSnapshot:
        return TaskSnapshot(
            id=self.id,
            kind=self.kind,
            status_str=self._status.value,
            command=self.command,
            is_running=self.is_running,
        )

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

        Shell tasks write to their pty/stdin. Subagent tasks raise an error.
        """

    @abstractmethod
    async def kill(self) -> None:
        """Terminate the task and transition it to a terminal status."""

    @abstractmethod
    async def wait(self) -> None:
        """Block until the task reaches a terminal status."""
