import asyncio
import logging
import os

from textual.app import ComposeResult
from textual.containers import Vertical

from core.models_catalog import catalog
from widgets.chat_input import ChatInput
from widgets.chat_view import ChatView
from widgets.command_suggestions import CommandSuggestions
from widgets.status_footer import StatusFooter

logger = logging.getLogger("johnston.app")


class LifecycleMixin:
    """Compose, mount, unmount and initial setup handling for JohnstonApp."""

    def compose(self) -> ComposeResult:
        with Vertical(id="app-container"):
            yield ChatView(id="chat-view")
            yield CommandSuggestions(id="command-suggestions")
            yield ChatInput(id="message-input", show_line_numbers=False)
            yield StatusFooter(id="status-footer")

    def on_mount(self) -> None:
        """Instant focus on start, background catalog refresh and status bar refresh"""
        self.is_app_active = True
        self.query_one("#message-input", ChatInput).focus()
        if getattr(self, "resume_session_id", None):
            self.load_session_ui(self.resume_session_id)
        self.refresh_status_footer()
        asyncio.create_task(catalog.refresh())
        asyncio.create_task(self._check_initial_setup())

    async def _check_initial_setup(self) -> None:
        """Auto-prompt for provider/model selection on first launch if unconfigured"""
        if getattr(self, "resume_session_id", None) or os.environ.get("PYTEST_CURRENT_TEST"):
            return
        providers = self.pm.load_providers()
        connected = any(self.pm.is_provider_connected(k, v) for k, v in providers.items())
        if not connected:
            from core.commands import ProvidersCommand
            await ProvidersCommand().execute(self)
        elif not getattr(getattr(self, "agent", None), "model", ""):
            from core.commands import ModelsCommand
            await ModelsCommand().execute(self)

    def on_unmount(self) -> None:
        """Clean up all running MCP servers and background processes when closing application"""
        self.is_app_active = False
        for task in getattr(self, "background_tasks", []):
            try:
                if hasattr(task, "kill_sync"):
                    task.kill_sync()
                elif hasattr(task, "kill") and asyncio.iscoroutinefunction(task.kill):
                    asyncio.create_task(task.kill())
                elif hasattr(task, "process") and task.process:
                    try:
                        task.process.terminate()
                    except Exception as err:
                        logger.debug(f"Process termination error: {err}")
                if hasattr(task, "read_task") and task.read_task:
                    task.read_task.cancel()
            except Exception as err:
                logger.debug(f"Task cleanup error: {err}")

        try:
            self.save_current_session()
        except Exception as err:
            logger.debug(f"Unmount session save error: {err}")

        try:
            from core.mcp_manager import get_mcp_manager

            get_mcp_manager().stop_all()
        except Exception as err:
            logger.debug(f"MCP cleanup error: {err}")

    def refresh_status_footer(self) -> None:
        """Refresh status bar with directory, provider, model, context, tokens, cost, and subagents"""
        try:
            footer = self.query_one("#status-footer", StatusFooter)
            footer.refresh_footer()
        except Exception as e:
            logger.debug(f"Error refreshing status footer: {e}")
