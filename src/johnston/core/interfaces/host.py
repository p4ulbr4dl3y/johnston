"""Host runtime interfaces and null implementations."""
from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class UserInteractionHost(Protocol):
    """Protocol for user-facing interactive prompts and permissions."""

    async def ask_user(self, questions: list[dict[str, Any]]) -> str | Any:
        """Prompt user with questions and return response."""
        ...

    async def confirm_permission(
        self,
        tool_name: str,
        args: dict[str, Any],
        reason: str = "",
        perm_name: str | None = None,
        is_subagent: bool = False,
        subagent_role: str = "",
        server_name: str | None = None,
        *call_args: Any,
        **kwargs: Any,
    ) -> bool:
        """Request user permission confirmation for a tool execution."""
        ...


@runtime_checkable
class ExecutionObserverHost(Protocol):
    """Protocol for observing execution events and plan updates."""

    def on_subagent_tool_completed(self, session_id: str, status: str, result: str = "") -> None:
        """Notify host that a subagent tool invocation finished."""
        ...

    def on_plan_update(self, plan: list[dict[str, Any]], status: str = "", *args: Any, **kwargs: Any) -> None:
        """Notify host of an updated execution plan."""
        ...


@runtime_checkable
class ShellTaskHost(Protocol):
    """Protocol for managing active foreground shell tasks."""

    def register_foreground_shell_task(self, task_id: str, task: Any) -> None:
        """Register an active foreground shell task."""
        ...

    def cleanup_foreground_shell_task(self, task_id: str) -> None:
        """Clean up an active foreground shell task upon exit or conversion."""
        ...

    def get_foreground_shell_task(self, task_id: str) -> Any | None:
        """Retrieve an active foreground shell task by id."""
        ...


@runtime_checkable
class HostProtocol(UserInteractionHost, ExecutionObserverHost, ShellTaskHost, Protocol):
    """Protocol defining the host/UI runtime capabilities required by core and tools."""

    @property
    def task_manager(self) -> Any:
        ...

    @property
    def current_session_id(self) -> str | None:
        ...

    @property
    def project_dir(self) -> str:
        ...

    pm: Any | None = None
    sandbox_enabled: bool = False
    is_read_only: bool = False
    message_queue: list[Any] | None = None
    session: Any | None = None

    def trigger_ai_response(self, prompt: str, show_in_ui: bool = False) -> None:
        """Trigger an AI response generation or enqueue it."""
        ...

    def refresh_status_footer(self) -> None:
        """Request a refresh of the status footer widget."""
        ...

    def attach_shell_widget(
        self,
        task_id: str,
        widget: Any,
        log_path: str | None = None,
        is_background: bool = False,
    ) -> None:
        """Attach a shell tool card widget to a task id for live status updates."""
        ...

    def detach_shell_widget(self, task_id: str) -> None:
        """Detach a shell tool card widget for a task id."""
        ...

    def terminate_task_widget(
        self,
        task_id: str,
        output: str = "[killed]",
        status: str = "done",
    ) -> None:
        """Safely terminate and detach linked UI widget for a killed task."""
        ...


class NullHost:
    """Headless / no-op host implementation for testing or non-UI execution."""

    def __init__(
        self,
        project_dir: str = "",
        current_session_id: str | None = None,
        task_manager: Any = None,
        pm: Any = None,
        sandbox_enabled: bool = False,
        is_read_only: bool = False,
        session: Any = None,
        message_queue: list[Any] | None = None,
    ) -> None:
        self.project_dir: str = project_dir or os.getcwd()
        self.current_session_id: str | None = current_session_id
        self.task_manager: Any = task_manager
        self.pm: Any = pm
        self.sandbox_enabled: bool = sandbox_enabled
        self.is_read_only: bool = is_read_only
        self.session: Any = session
        self.message_queue: list[Any] = message_queue if message_queue is not None else []
        self._foreground_shell_tasks: dict[str, Any] = {}

    async def ask_user(self, questions: list[dict[str, Any]]) -> str | Any:
        return ""

    async def confirm_permission(
        self,
        tool_name: str,
        args: dict[str, Any],
        reason: str = "",
        perm_name: str | None = None,
        is_subagent: bool = False,
        subagent_role: str = "",
        server_name: str | None = None,
        *call_args: Any,
        **kwargs: Any,
    ) -> bool:
        return False

    def trigger_ai_response(self, prompt: str, show_in_ui: bool = False) -> None:
        pass

    def refresh_status_footer(self) -> None:
        pass

    def on_subagent_tool_completed(self, session_id: str, status: str, result: str = "") -> None:
        pass

    def on_plan_update(self, plan: list[dict[str, Any]], status: str = "", *args: Any, **kwargs: Any) -> None:
        pass

    def attach_shell_widget(
        self,
        task_id: str,
        widget: Any,
        log_path: str | None = None,
        is_background: bool = False,
    ) -> None:
        pass

    def detach_shell_widget(self, task_id: str) -> None:
        pass

    def register_foreground_shell_task(self, task_id: str, task: Any) -> None:
        self._foreground_shell_tasks[task_id] = task

    def cleanup_foreground_shell_task(self, task_id: str) -> None:
        self._foreground_shell_tasks.pop(task_id, None)

    def get_foreground_shell_task(self, task_id: str) -> Any | None:
        return self._foreground_shell_tasks.get(task_id)

    def terminate_task_widget(
        self,
        task_id: str,
        output: str = "[killed]",
        status: str = "done",
    ) -> None:
        pass


__all__ = [
    "ExecutionObserverHost",
    "HostProtocol",
    "NullHost",
    "ShellTaskHost",
    "UserInteractionHost",
]
