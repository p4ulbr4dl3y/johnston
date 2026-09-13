"""Task and shell widget registry management."""
from __future__ import annotations

from typing import Any

__all__ = ["TaskWidgetRegistry"]


class TaskWidgetRegistry:
    """Clean, fully-typed registry managing shell widgets, foreground tasks, and subagent tools."""

    def __init__(
        self,
        background_shell_widgets: dict[str, Any] | None = None,
        foreground_shell_tasks: dict[str, Any] | None = None,
        subagent_tools: dict[str, Any] | None = None,
    ) -> None:
        self._background_shell_widgets: dict[str, Any] = (
            background_shell_widgets if background_shell_widgets is not None else {}
        )
        self._foreground_shell_tasks: dict[str, Any] = (
            foreground_shell_tasks if foreground_shell_tasks is not None else {}
        )
        self._subagent_tools: dict[str, Any] = (
            subagent_tools if subagent_tools is not None else {}
        )

    @property
    def background_shell_widgets(self) -> dict[str, Any]:
        """Dictionary of registered background shell widgets keyed by task_id."""
        return self._background_shell_widgets

    @background_shell_widgets.setter
    def background_shell_widgets(self, value: dict[str, Any]) -> None:
        self._background_shell_widgets = value

    @property
    def foreground_shell_tasks(self) -> dict[str, Any]:
        """Dictionary of registered foreground shell tasks keyed by task_id."""
        return self._foreground_shell_tasks

    @foreground_shell_tasks.setter
    def foreground_shell_tasks(self, value: dict[str, Any]) -> None:
        self._foreground_shell_tasks = value

    @property
    def subagent_tools(self) -> dict[str, Any]:
        """Dictionary of registered subagent tools keyed by session_id/task_id."""
        return self._subagent_tools

    @subagent_tools.setter
    def subagent_tools(self, value: dict[str, Any]) -> None:
        self._subagent_tools = value

    def attach_shell_widget(
        self,
        task_id: str,
        widget: Any,
        log_path: str | None = None,
        is_background: bool = False,
    ) -> None:
        """Attach a shell tool card widget to a task id for live status updates."""
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
        if not isinstance(self._background_shell_widgets, dict):
            self._background_shell_widgets = {}
        self._background_shell_widgets[task_id] = widget

    def detach_shell_widget(self, task_id: str) -> None:
        """Detach a shell tool card widget for a task id."""
        if isinstance(self._background_shell_widgets, dict):
            self._background_shell_widgets.pop(task_id, None)

    def register_foreground_shell_task(self, task_id: str, task: Any) -> None:
        """Register an active foreground shell task."""
        if not isinstance(self._foreground_shell_tasks, dict):
            self._foreground_shell_tasks = {}
        self._foreground_shell_tasks[task_id] = task

    def cleanup_foreground_shell_task(self, task_id: str) -> None:
        """Clean up an active foreground shell task upon exit or conversion."""
        if isinstance(self._foreground_shell_tasks, dict):
            self._foreground_shell_tasks.pop(task_id, None)

    def get_foreground_shell_task(self, task_id: str) -> Any | None:
        """Retrieve an active foreground shell task by id."""
        if isinstance(self._foreground_shell_tasks, dict):
            return self._foreground_shell_tasks.get(task_id)
        return None

    def get_foreground_shell_tasks(self) -> list[Any]:
        """Retrieve all active foreground shell tasks."""
        if isinstance(self._foreground_shell_tasks, dict):
            return list(self._foreground_shell_tasks.values())
        return []

    def terminate_task_widget(
        self,
        task_id: str,
        output: str = "[killed]",
        status: str = "done",
    ) -> None:
        """Safely terminate and detach linked UI widget for a killed task."""
        if isinstance(self._background_shell_widgets, dict):
            widget = self._background_shell_widgets.pop(task_id, None)
            if widget is not None and hasattr(widget, "set_result"):
                try:
                    widget.set_result(output, status=status)
                except Exception:
                    pass
        if isinstance(self._subagent_tools, dict):
            self._subagent_tools.pop(task_id, None)

    def register_subagent_tool(self, session_id: str, tool: Any) -> None:
        """Register an active subagent tool."""
        if not isinstance(self._subagent_tools, dict):
            self._subagent_tools = {}
        self._subagent_tools[session_id] = tool

    def cleanup_subagent_tool(self, session_id: str) -> None:
        """Clean up an active subagent tool."""
        if isinstance(self._subagent_tools, dict):
            self._subagent_tools.pop(session_id, None)

    def get_subagent_tool(self, session_id: str) -> Any | None:
        """Retrieve an active subagent tool by session id."""
        if isinstance(self._subagent_tools, dict):
            return self._subagent_tools.get(session_id)
        return None

    def get_subagent_tools(self) -> dict[str, Any]:
        """Retrieve all active subagent tools."""
        if isinstance(self._subagent_tools, dict):
            return dict(self._subagent_tools)
        return {}

    def clear(self) -> None:
        """Clear all registered shell widgets, tasks, and subagent tools."""
        if isinstance(self._background_shell_widgets, dict):
            self._background_shell_widgets.clear()
        if isinstance(self._foreground_shell_tasks, dict):
            self._foreground_shell_tasks.clear()
        if isinstance(self._subagent_tools, dict):
            self._subagent_tools.clear()
