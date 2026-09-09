"""Mixin for managing shell tool widgets and foreground shell task handles."""
from __future__ import annotations

from typing import Any


class TaskWidgetRegistryMixin:
    """Provides methods for registering, retrieving, and terminating shell widgets and tasks."""

    _background_shell_widgets: dict[str, Any]
    _foreground_shell_tasks: dict[str, Any]
    _subagent_tools: dict[str, Any]

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
        reg = getattr(self, "_background_shell_widgets", None)
        if not isinstance(reg, dict):
            reg = {}
            self._background_shell_widgets = reg
        reg[task_id] = widget

    def detach_shell_widget(self, task_id: str) -> None:
        """Detach a shell tool card widget for a task id."""
        reg = getattr(self, "_background_shell_widgets", None)
        if isinstance(reg, dict):
            reg.pop(task_id, None)

    def register_foreground_shell_task(self, task_id: str, task: Any) -> None:
        """Register an active foreground shell task."""
        fg = getattr(self, "_foreground_shell_tasks", None)
        if not isinstance(fg, dict):
            fg = {}
            self._foreground_shell_tasks = fg
        fg[task_id] = task

    def cleanup_foreground_shell_task(self, task_id: str) -> None:
        """Clean up an active foreground shell task upon exit or conversion."""
        fg = getattr(self, "_foreground_shell_tasks", None)
        if isinstance(fg, dict):
            fg.pop(task_id, None)

    def get_foreground_shell_task(self, task_id: str) -> Any | None:
        """Retrieve an active foreground shell task by id."""
        fg = getattr(self, "_foreground_shell_tasks", None)
        if isinstance(fg, dict):
            return fg.get(task_id)
        return None

    def get_foreground_shell_tasks(self) -> list[Any]:
        """Retrieve all active foreground shell tasks."""
        fg = getattr(self, "_foreground_shell_tasks", None)
        if isinstance(fg, dict):
            return list(fg.values())
        return []

    def terminate_task_widget(
        self,
        task_id: str,
        output: str = "[killed]",
        status: str = "done",
    ) -> None:
        """Safely terminate and detach linked UI widget for a killed task."""
        reg = getattr(self, "_background_shell_widgets", None)
        if isinstance(reg, dict):
            widget = reg.pop(task_id, None)
            if widget is not None and hasattr(widget, "set_result"):
                try:
                    widget.set_result(output, status=status)
                except Exception:
                    pass
        sub_tools = getattr(self, "_subagent_tools", None)
        if isinstance(sub_tools, dict):
            sub_tools.pop(task_id, None)
