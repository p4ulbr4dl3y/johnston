"""Mixin for managing shell tool widgets and foreground shell task handles."""
from __future__ import annotations

from typing import Any

from johnston.tui.app.task_registry import TaskWidgetRegistry

__all__ = ["TaskWidgetRegistryMixin"]


class TaskWidgetRegistryMixin:
    """Provides methods for registering, retrieving, and terminating shell widgets and tasks."""

    _task_registry_instance: TaskWidgetRegistry | None = None

    @property
    def task_registry(self) -> TaskWidgetRegistry:
        """Get or initialize the underlying TaskWidgetRegistry."""
        reg = getattr(self, "_task_registry_instance", None)
        if not isinstance(reg, TaskWidgetRegistry):
            reg = TaskWidgetRegistry()
            object.__setattr__(self, "_task_registry_instance", reg)
        return reg

    @task_registry.setter
    def task_registry(self, value: TaskWidgetRegistry) -> None:
        object.__setattr__(self, "_task_registry_instance", value)

    @property
    def _task_registry(self) -> TaskWidgetRegistry:
        return self.task_registry

    @_task_registry.setter
    def _task_registry(self, value: TaskWidgetRegistry) -> None:
        self.task_registry = value

    @property
    def _background_shell_widgets(self) -> dict[str, Any]:
        if hasattr(self, "__dict__") and "_background_shell_widgets" in self.__dict__:
            val = self.__dict__["_background_shell_widgets"]
            if val is not self.task_registry.background_shell_widgets:
                self.task_registry.background_shell_widgets = val
        return self.task_registry.background_shell_widgets

    @_background_shell_widgets.setter
    def _background_shell_widgets(self, value: dict[str, Any]) -> None:
        self.task_registry.background_shell_widgets = value
        if hasattr(self, "__dict__") and "_background_shell_widgets" in self.__dict__:
            self.__dict__["_background_shell_widgets"] = value

    @_background_shell_widgets.deleter
    def _background_shell_widgets(self) -> None:
        self.task_registry.background_shell_widgets = {}
        if hasattr(self, "__dict__"):
            self.__dict__.pop("_background_shell_widgets", None)

    @property
    def _foreground_shell_tasks(self) -> dict[str, Any]:
        if hasattr(self, "__dict__") and "_foreground_shell_tasks" in self.__dict__:
            val = self.__dict__["_foreground_shell_tasks"]
            if val is not self.task_registry.foreground_shell_tasks:
                self.task_registry.foreground_shell_tasks = val
        return self.task_registry.foreground_shell_tasks

    @_foreground_shell_tasks.setter
    def _foreground_shell_tasks(self, value: dict[str, Any]) -> None:
        self.task_registry.foreground_shell_tasks = value
        if hasattr(self, "__dict__") and "_foreground_shell_tasks" in self.__dict__:
            self.__dict__["_foreground_shell_tasks"] = value

    @_foreground_shell_tasks.deleter
    def _foreground_shell_tasks(self) -> None:
        self.task_registry.foreground_shell_tasks = {}
        if hasattr(self, "__dict__"):
            self.__dict__.pop("_foreground_shell_tasks", None)

    @property
    def _subagent_tools(self) -> dict[str, Any]:
        if hasattr(self, "__dict__") and "_subagent_tools" in self.__dict__:
            val = self.__dict__["_subagent_tools"]
            if val is not self.task_registry.subagent_tools:
                self.task_registry.subagent_tools = val
        return self.task_registry.subagent_tools

    @_subagent_tools.setter
    def _subagent_tools(self, value: dict[str, Any]) -> None:
        self.task_registry.subagent_tools = value
        if hasattr(self, "__dict__") and "_subagent_tools" in self.__dict__:
            self.__dict__["_subagent_tools"] = value

    @_subagent_tools.deleter
    def _subagent_tools(self) -> None:
        self.task_registry.subagent_tools = {}
        if hasattr(self, "__dict__"):
            self.__dict__.pop("_subagent_tools", None)

    def attach_shell_widget(
        self,
        task_id: str,
        widget: Any,
        log_path: str | None = None,
        is_background: bool = False,
    ) -> None:
        """Attach a shell tool card widget to a task id for live status updates."""
        self.task_registry.attach_shell_widget(
            task_id=task_id,
            widget=widget,
            log_path=log_path,
            is_background=is_background,
        )

    def detach_shell_widget(self, task_id: str) -> None:
        """Detach a shell tool card widget for a task id."""
        self.task_registry.detach_shell_widget(task_id=task_id)

    def register_foreground_shell_task(self, task_id: str, task: Any) -> None:
        """Register an active foreground shell task."""
        self.task_registry.register_foreground_shell_task(task_id=task_id, task=task)

    def cleanup_foreground_shell_task(self, task_id: str) -> None:
        """Clean up an active foreground shell task upon exit or conversion."""
        self.task_registry.cleanup_foreground_shell_task(task_id=task_id)

    def get_foreground_shell_task(self, task_id: str) -> Any | None:
        """Retrieve an active foreground shell task by id."""
        return self.task_registry.get_foreground_shell_task(task_id=task_id)

    def get_foreground_shell_tasks(self) -> list[Any]:
        """Retrieve all active foreground shell tasks."""
        return self.task_registry.get_foreground_shell_tasks()

    def terminate_task_widget(
        self,
        task_id: str,
        output: str = "[killed]",
        status: str = "done",
    ) -> None:
        """Safely terminate and detach linked UI widget for a killed task."""
        self.task_registry.terminate_task_widget(
            task_id=task_id,
            output=output,
            status=status,
        )
