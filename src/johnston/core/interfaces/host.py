"""Host runtime interfaces and null implementations."""
from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class HostProtocol(Protocol):
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

    def ask_user(self, questions: list[dict[str, Any]]) -> Any:
        """Prompt user with questions and return response."""
        ...

    def confirm_permission(
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

    def trigger_ai_response(self, prompt: str, show_in_ui: bool = False) -> None:
        """Trigger an AI response generation or enqueue it."""
        ...

    def refresh_status_footer(self) -> None:
        """Request a refresh of the status footer widget."""
        ...

    def on_subagent_tool_completed(self, session_id: str, status: str, result: str = "") -> None:
        """Notify host that a subagent tool invocation finished."""
        ...

    def on_plan_update(self, plan: list[dict[str, Any]], status: str = "", *args: Any, **kwargs: Any) -> None:
        """Notify host of an updated execution plan."""
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

    def register_foreground_shell_task(self, task_id: str, task: Any) -> None:
        """Register an active foreground shell task."""
        ...

    def cleanup_foreground_shell_task(self, task_id: str) -> None:
        """Clean up an active foreground shell task upon exit or conversion."""
        ...

    def get_foreground_shell_task(self, task_id: str) -> Any | None:
        """Retrieve an active foreground shell task by id."""
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
    ) -> None:
        self.project_dir: str = project_dir or os.getcwd()
        self.current_session_id: str | None = current_session_id
        self.task_manager: Any = task_manager
        self.message_queue: list[Any] = []
        self._background_shell_widgets: dict[str, Any] = {}
        self._foreground_shell_tasks: dict[str, Any] = {}
        self._subagent_tools: dict[str, Any] = {}

    async def ask_user(self, questions: list[dict[str, Any]]) -> Any:
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
        if widget is None:
            return
        if is_background:
            if hasattr(widget, "mark_background"):
                try:
                    widget.mark_background(task_id, log_path)
                except Exception:
                    pass
            else:
                try:
                    setattr(widget, "background_task_id", task_id)
                    setattr(widget, "task_id", task_id)
                    if log_path:
                        setattr(widget, "log_path", log_path)
                except Exception:
                    pass
        self._background_shell_widgets[task_id] = widget

    def detach_shell_widget(self, task_id: str) -> None:
        self._background_shell_widgets.pop(task_id, None)

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
        widget = self._background_shell_widgets.pop(task_id, None)
        if widget is not None and hasattr(widget, "set_result"):
            try:
                widget.set_result(output, status=status)
            except Exception:
                pass
        self._subagent_tools.pop(task_id, None)
