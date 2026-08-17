import asyncio
import logging
import os

from textual.app import ComposeResult
from textual.containers import Vertical

from core.models_catalog import catalog
from widgets.chat_input import ChatInput
from widgets.command_suggestions import CommandSuggestions
from widgets.presentation.widgets.chat_container import ChatView
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
        from core.infrastructure.mcp import get_mcp_manager

        self.refresh_status_footer()
        asyncio.create_task(catalog.refresh())
        asyncio.create_task(get_mcp_manager().ensure_tools_ready_async())
        asyncio.create_task(self._check_initial_setup())

    async def _check_initial_setup(self) -> None:
        """Auto-prompt for provider/model selection on first launch if unconfigured"""
        if getattr(self, "resume_session_id", None) or os.environ.get("PYTEST_CURRENT_TEST"):
            return
        providers = self.pm.load_providers()
        connected = any(self.pm.is_provider_connected(k, v) for k, v in providers.items())
        if not connected:
            from widgets.commands import ProvidersCommand

            await ProvidersCommand().execute(self)
        elif not getattr(getattr(self, "agent", None), "model", ""):
            from widgets.commands import ModelsCommand

            await ModelsCommand().execute(self)

    def on_unmount(self) -> None:
        """Clean up all running MCP servers and background processes when closing application"""
        self.is_app_active = False

        # Cancel an in-flight rewind git-restore task (kept on the agent by
        # rewind_session) so shutdown does not leave the worktree half-restored.
        git_task = getattr(getattr(self, "agent", None), "rewind_git_restore_task", None)
        if git_task is not None and not git_task.done():
            git_task.cancel()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        try:
            if loop is not None:
                loop.create_task(self._kill_all_tasks())
            else:
                self._kill_all_tasks_sync()
        except Exception as err:
            logger.debug(f"Background task cleanup error: {err}")
        try:
            from core.application.session.stream import cancel_running_subagents

            cancel_running_subagents(self.sm)
        except Exception as err:
            logger.debug(f"Subagent cleanup error: {err}")

        try:
            self.save_current_session()
        except Exception as err:
            logger.debug(f"Unmount session save error: {err}")

        try:
            from core.infrastructure.mcp import get_mcp_manager

            get_mcp_manager().stop_all()
        except Exception as err:
            logger.debug(f"MCP cleanup error: {err}")

    async def _kill_all_tasks(self) -> None:
        try:
            await self.task_manager.kill_all()
        except Exception:
            pass

    def _kill_all_tasks_sync(self) -> None:
        for task in list(self.task_manager):
            try:
                kill = getattr(task, "kill", None)
                if callable(kill) and asyncio.iscoroutinefunction(kill):
                    asyncio.create_task(kill())
                elif callable(kill):
                    kill()
            except Exception:
                pass

    def refresh_status_footer(self) -> None:
        """Refresh status bar with directory, provider, model, context, tokens, cost, and subagents"""
        try:
            footer = self.query_one("#status-footer", StatusFooter)
            footer.refresh_footer()
        except Exception as e:
            logger.debug(f"Error refreshing status footer: {e}")
