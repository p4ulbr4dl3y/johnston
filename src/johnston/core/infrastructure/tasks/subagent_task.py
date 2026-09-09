"""Subagent task: a BaseTask backed by an AgentSession.

Adapts an AgentSession into the unified TaskManager contract, providing
status mapping, cancellation, and execution awaiting.
"""

import asyncio
import time
from typing import Any, Optional

from johnston.core.domain.entities.session import SessionStatus
from johnston.core.infrastructure.tasks.task import BaseTask, TaskStatus


class SubagentTask(BaseTask):
    """BaseTask implementation wrapping an AgentSession subagent."""

    def __init__(
        self,
        session: Any,
        store: Any = None,
        async_task: Any = None,
    ) -> None:
        self.session = session
        self.store = store
        self._async_task = async_task or getattr(session, "async_task", None)
        self.session_id = getattr(session, "parent_id", None) or getattr(session, "id", None)
        self.process = None
        self.was_killed = False
        self.is_background = True
        self._completed_at: Optional[float] = None

        role = getattr(session, "role", "worker")
        title = getattr(session, "title", "")
        super().__init__(
            task_id=session.id,
            kind="subagent",
            command=f"[{role}] {title}",
            status=self._calculate_status(),
            created_at=getattr(session, "created_at", None),
        )

    @property
    def async_task(self) -> Any:
        sess_task = getattr(self.session, "async_task", None)
        if sess_task is not None:
            return sess_task
        return self._async_task

    @async_task.setter
    def async_task(self, val: Any) -> None:
        self._async_task = val
        if hasattr(self.session, "async_task"):
            self.session.async_task = val

    def __repr__(self) -> str:
        return f"SubagentTask(id={self.id!r}, status={self.status.value})"

    # -- status ------------------------------------------------------------

    def _calculate_status(self) -> TaskStatus:
        if getattr(self, "was_killed", False) or getattr(self, "_status", None) == TaskStatus.KILLED:
            return TaskStatus.KILLED

        st = getattr(self.session, "status", None)
        if hasattr(st, "value"):
            st_val = str(st.value).lower()
        else:
            st_val = str(st or "").lower()

        if st_val in (SessionStatus.CANCELLED.value, "cancelled", "canceled", "killed"):
            return TaskStatus.KILLED
        if st_val in (SessionStatus.ERROR.value, "error", "failed"):
            return TaskStatus.ERROR
        if st_val in (SessionStatus.COMPLETED.value, "completed", "done", "finished"):
            return TaskStatus.COMPLETED

        task = self.async_task
        task_active = task is not None and hasattr(task, "done") and not task.done()
        session_active = st_val in (
            SessionStatus.ACTIVE.value,
            SessionStatus.RUNNING.value,
            "running",
            "active",
        )
        if task_active or session_active:
            return TaskStatus.RUNNING

        return TaskStatus.COMPLETED

    @property
    def status(self) -> TaskStatus:
        return self._calculate_status()

    @status.setter
    def status(self, value: TaskStatus) -> None:
        self._status = value

    @property
    def completed_at(self) -> Optional[float]:
        if self._completed_at is not None:
            return self._completed_at
        if not self.is_active:
            return getattr(self.session, "updated_at", None) or self.created_at
        return None

    @completed_at.setter
    def completed_at(self, value: Optional[float]) -> None:
        self._completed_at = value

    # -- lifecycle ---------------------------------------------------------

    async def kill(self) -> None:
        from johnston.core.application.session.subagent_service import SubagentService

        SubagentService.kill_subagent(self.session, self.store)
        self.was_killed = True
        self.completed_at = time.time()
        self._status = TaskStatus.KILLED

    def kill_sync(self) -> None:
        from johnston.core.application.session.subagent_service import SubagentService

        SubagentService.kill_subagent(self.session, self.store)
        self.was_killed = True
        self.completed_at = time.time()
        self._status = TaskStatus.KILLED

    async def wait(self) -> None:
        if self.async_task:
            try:
                await self.async_task
            except (asyncio.CancelledError, Exception):
                pass

    # -- io ----------------------------------------------------------------

    async def read(self) -> str:
        messages = getattr(self.session, "messages", None)
        if messages:
            parts = []
            for msg in messages:
                if isinstance(msg, dict):
                    text = msg.get("text") or msg.get("result_text") or ""
                    if text:
                        parts.append(str(text))
                elif isinstance(msg, str):
                    parts.append(msg)
            if parts:
                return "\n".join(parts)

        history = getattr(self.session, "agent_history", None)
        if history:
            for msg in reversed(history):
                if isinstance(msg, dict) and msg.get("role") == "assistant":
                    content = msg.get("content")
                    if isinstance(content, str) and content:
                        return content
                    if isinstance(content, list):
                        text_chunks = [
                            c.get("text", "")
                            for c in content
                            if isinstance(c, dict) and c.get("text")
                        ]
                        if text_chunks:
                            return "\n".join(text_chunks)

        return getattr(self.session, "prompt", "") or ""

    async def tail(self, max_chars: int = 4000) -> str:
        content = await self.read()
        if len(content) > max_chars:
            return content[-max_chars:]
        return content
