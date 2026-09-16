"""Lifecycle mixin for JohnstonApp.

Textual requires compose() to yield child widgets in the App class.
Delegates mount, unmount, project switching, and status refresh to AppLifecycleService.
"""
from __future__ import annotations

import logging
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical

from johnston.core import client as core_bridge
from johnston.tui.app.lifecycle_service import (
    AppLifecycleService,
    _close_catalog_sync,
    _close_tools_sync,
)
from johnston.tui.presentation.widgets.attachment_bar import AttachmentBar
from johnston.tui.presentation.widgets.chat_container import ChatView
from johnston.tui.presentation.widgets.chat_input import ChatInput
from johnston.tui.presentation.widgets.command_suggestions import CommandSuggestions
from johnston.tui.presentation.widgets.plan_notch import PlanNotchContainer
from johnston.tui.presentation.widgets.status_footer import StatusFooter

install_asyncio_exception_handler = core_bridge.install_asyncio_exception_handler

logger = logging.getLogger("johnston.app")

__all__ = [
    "LifecycleMixin",
    "install_asyncio_exception_handler",
    "_close_catalog_sync",
    "_close_tools_sync",
]


class LifecycleMixin:
    """Compose, mount, unmount and initial setup handling for JohnstonApp."""

    @classmethod
    def _resolve_lifecycle_service(cls, host: Any) -> AppLifecycleService:
        service = getattr(host, "lifecycle_service", None)
        if service is None or getattr(service, "app", None) is not host:
            service = AppLifecycleService(host)
            try:
                host.lifecycle_service = service
            except Exception:
                pass
        return service

    def _get_lifecycle_service(self) -> AppLifecycleService:
        """Get or lazily create AppLifecycleService for this app."""
        return LifecycleMixin._resolve_lifecycle_service(self)

    def compose(self) -> ComposeResult:
        yield PlanNotchContainer(id="plan-notch-container")
        with Vertical(id="app-container"):
            yield ChatView(id="chat-view")
            yield CommandSuggestions(id="command-suggestions")
            yield AttachmentBar(id="attachment-bar")
            yield ChatInput(id="message-input", show_line_numbers=False)
            yield StatusFooter(id="status-footer")

    def on_mount(self) -> None:
        """Instant focus on start, background catalog refresh and status bar refresh"""
        LifecycleMixin._resolve_lifecycle_service(self).handle_mount()

    async def _check_initial_setup(self) -> None:
        """Auto-prompt for provider/model selection on first launch if unconfigured"""
        await LifecycleMixin._resolve_lifecycle_service(self).check_initial_setup()

    def on_unmount(self) -> None:
        """Clean up all running MCP servers and background processes when closing application"""
        LifecycleMixin._resolve_lifecycle_service(self).handle_unmount()

    async def _kill_all_tasks(self) -> None:
        await LifecycleMixin._resolve_lifecycle_service(self).kill_all_tasks()

    def _kill_all_tasks_sync(self) -> None:
        LifecycleMixin._resolve_lifecycle_service(self).kill_all_tasks_sync()

    def refresh_status_footer(self) -> None:
        """Refresh status bar with directory, provider, model, context, tokens, cost, and subagents"""
        LifecycleMixin._resolve_lifecycle_service(self).refresh_status_footer()

    def switch_project_dir(self, new_dir: str, branch: str = "") -> None:
        LifecycleMixin._resolve_lifecycle_service(self).switch_project_dir(new_dir, branch)
