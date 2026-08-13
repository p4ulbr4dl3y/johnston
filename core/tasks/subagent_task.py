"""Subagent task: a BaseTask wrapped around an AgentSession.

A subagent task's output is the session's message stream and its lifecycle is
reflected in the session status. This wrapper translates between the generic
BaseTask contract and the session/AgentSession model, without touching the
existing subagent machinery.
"""

from typing import Any

from core.session_manager import (
    MAIN_STATUS_ACTIVE,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_ERROR,
    SUBAGENT_STATUS_RUNNING,
)
from core.tasks.task import BaseTask, TaskStatus
from tools.base import format_tool_error

# Maps session status names onto TaskStatus. Session statuses are loose
# strings, so fall back permissively (subagent running -> queued/running).
_SESSION_STATUS_TO_TASK = {
    SUBAGENT_STATUS_RUNNING: TaskStatus.RUNNING,
    MAIN_STATUS_ACTIVE: TaskStatus.RUNNING,
    STATUS_COMPLETED: TaskStatus.COMPLETED,
    STATUS_CANCELLED: TaskStatus.KILLED,
    STATUS_ERROR: TaskStatus.ERROR,
}


class SubagentTask(BaseTask):
    """Adapter over an AgentSession (kind="subagent") exposing the BaseTask API."""

    def __init__(
        self,
        task_id: str,
        session: Any,
        store: Any = None,
        *,
        command: str = "",
        description: str = "",
    ) -> None:
        super().__init__(
            task_id,
            kind="subagent",
            command=command or description or session.description or "",
            status=self._map_status(getattr(session, "status", "")),
        )
        self.session = session
        self.store = store
        self.description = description or session.description or ""

    def __repr__(self) -> str:
        return f"SubagentTask(id={self.id!r}, status={self._status.value})"

    # -- status mapping -----------------------------------------------------

    def _map_status(self, status: str) -> TaskStatus:
        return _SESSION_STATUS_TO_TASK.get(status) or TaskStatus.QUEUED

    @property
    def _task_status(self) -> TaskStatus:
        return self._map_status(getattr(self.session, "status", ""))

    @property
    def status(self) -> TaskStatus:
        # Always reflect the live session status.
        self._status = self._task_status
        return self._status

    @status.setter
    def status(self, value: TaskStatus) -> None:
        self._status = value

    # -- output -------------------------------------------------------------

    def _messages_text(self) -> str:
        parts = []
        for m in getattr(self.session, "messages", []) or []:
            mtype = m.get("type", "")
            text = m.get("text") or m.get("result_text") or ""
            if not text:
                continue
            if mtype == "tool":
                parts.append(f"[tool] {text}")
            elif mtype == "thinking":
                parts.append(f"[thinking] {text}")
            else:
                parts.append(text)
        return "\n".join(parts)

    async def read(self) -> str:
        return self._messages_text()

    async def tail(self, max_chars: int = 4000) -> str:
        text = self._messages_text()
        return text if len(text) <= max_chars else text[-max_chars:]

    async def wait(self) -> None:
        # Poll until the session reaches a terminal status.
        if not self.is_running:
            return
        async_task = getattr(self.session, "async_task", None)
        if async_task is not None:
            try:
                await async_task
            except Exception:
                pass
        else:
            import asyncio

            while self.is_running:
                await asyncio.sleep(0.1)
                self._status = self._task_status

    # -- input (not supported) ---------------------------------------------

    async def send_input(self, text: str) -> str:
        return format_tool_error("subagent", "input is not supported for subagent tasks")

    # -- kill ---------------------------------------------------------------

    async def kill(self) -> None:
        async_task = getattr(self.session, "async_task", None)
        if async_task is not None and not async_task.done():
            try:
                async_task.cancel()
            except Exception:
                pass
        try:
            self.session.finish(STATUS_CANCELLED, "Cancelled by user")
        except Exception:
            pass
        if self.store is not None:
            try:
                self.store.save(self.session)
            except Exception:
                pass
        self._status = TaskStatus.KILLED
