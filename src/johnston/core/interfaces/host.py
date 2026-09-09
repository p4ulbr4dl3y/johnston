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
