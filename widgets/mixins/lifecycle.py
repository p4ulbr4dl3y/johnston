import asyncio
import logging
import os
import threading

from textual.app import ComposeResult
from textual.containers import Vertical

from core.infrastructure.platform.logging_setup import install_asyncio_exception_handler
from core.models_catalog import catalog
from widgets.chat_input import ChatInput
from widgets.command_suggestions import CommandSuggestions
from widgets.presentation.widgets.attachment_bar import AttachmentBar
from widgets.presentation.widgets.chat_container import ChatView
from widgets.presentation.widgets.plan_notch import PlanNotchContainer
from widgets.status_footer import StatusFooter

logger = logging.getLogger("johnston.app")


def _close_catalog_sync() -> None:
    """Run catalog.close() on a private loop (used from the shutdown thread)."""
    try:
        asyncio.run(catalog.close())
    except Exception as err:
        logger.debug(f"Catalog close error: {err}")


def _close_tools_sync() -> None:
    """Run aclose_tools() on a private loop (used from the shutdown thread)."""
    try:
        from tools.registry import aclose_tools

        asyncio.run(aclose_tools())
    except Exception as err:
        logger.debug(f"Tool instance close error: {err}")


class LifecycleMixin:
    """Compose, mount, unmount and initial setup handling for JohnstonApp."""

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
        install_asyncio_exception_handler()
        from widgets.app.theme_manager import prewarm_terminal_palette, theme_manager

        prewarm_terminal_palette()
        if hasattr(self, 'register_theme'):
            available = getattr(self, 'available_themes', {})
            for t in theme_manager.get_all_textual_themes():
                if t.name not in available:
                    self.register_theme(t)
            self.theme = theme_manager.current_theme.name
        self._theme_listener = lambda _: self.refresh_status_footer() if hasattr(self, "refresh_status_footer") else None
        theme_manager.add_listener(self._theme_listener)
        self.is_app_active = True
        self.query_one("#message-input", ChatInput).focus()
        if getattr(self, "resume_session_id", None):
            res_id = self.resume_session_id
            if hasattr(self, "sm") and self.sm.is_session_locked(res_id) is True:
                from widgets.presentation.screens.session_conflict import SessionConflictScreen

                def on_init_conflict(choice: str | None) -> None:
                    if choice == "steal":
                        self.sm.steal_session_lock(res_id)
                        self.load_session_ui(res_id)
                    elif choice == "readonly":
                        self.load_session_ui(res_id, read_only=True)
                    else:
                        new_id = self.sm.generate_session_id() if hasattr(self.sm, "generate_session_id") else ""
                        self.current_session_id = new_id
                        if hasattr(self.sm, "acquire_session_lock"):
                            self.sm.acquire_session_lock(new_id)
                        if hasattr(self.sm, "set_active_session_id"):
                            self.sm.set_active_session_id(new_id)
                        self.is_read_only = False
                        if hasattr(self, "notify"):
                            self.notify("Resume cancelled. Started new session.", severity="information")
                        if hasattr(self, "refresh_status_footer"):
                            self.refresh_status_footer()

                self.push_screen(SessionConflictScreen(res_id), callback=on_init_conflict)
            else:
                self.load_session_ui(res_id)
        else:
            if getattr(self, "current_session_id", None) and hasattr(self, "sm"):
                if hasattr(self.sm, "acquire_session_lock"):
                    self.sm.acquire_session_lock(self.current_session_id)
            if getattr(self, "resume_session_id", None) == "":
                from widgets.presentation.commands import ResumeCommand

                if hasattr(self, "create_tracked_task") and callable(self.create_tracked_task):
                    self.create_tracked_task(ResumeCommand().execute(self))
                else:
                    asyncio.create_task(ResumeCommand().execute(self))
        from core.infrastructure.mcp import get_mcp_manager

        catalog.load_cache()
        self.refresh_status_footer()

        async def _refresh_catalog_bg() -> None:
            try:
                await catalog.refresh(force=False)
            except Exception:
                pass

        if hasattr(self, "create_tracked_task") and callable(self.create_tracked_task):
            self.create_tracked_task(get_mcp_manager().ensure_tools_ready_async())
            self.create_tracked_task(self._check_initial_setup())
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                self.create_tracked_task(_refresh_catalog_bg())
        else:
            asyncio.create_task(get_mcp_manager().ensure_tools_ready_async())
            asyncio.create_task(self._check_initial_setup())
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                asyncio.create_task(_refresh_catalog_bg())

    async def _check_initial_setup(self) -> None:
        """Auto-prompt for provider/model selection on first launch if unconfigured"""
        if (
            getattr(self, "resume_session_id", None) is not None
            or os.environ.get("PYTEST_CURRENT_TEST")
            or not getattr(self, "is_app_active", True)
        ):
            return
        active_key = self.pm.get_active_provider_key()
        if not active_key or not self.pm.is_provider_connected(active_key):
            if not getattr(self, "is_app_active", True):
                return
            from widgets.presentation.commands import ProvidersCommand

            await ProvidersCommand().execute(self)
        elif not getattr(getattr(self, "agent", None), "model", ""):
            from widgets.presentation.commands import ModelsCommand

            await ModelsCommand().execute(self)

    def on_unmount(self) -> None:
        """Clean up all running MCP servers and background processes when closing application"""
        self.is_app_active = False

        for w in getattr(self, "workers", []):
            if getattr(w, "is_running", False):
                w.cancel()

        if hasattr(self, "_theme_listener"):
            try:
                from widgets.app.theme_manager import theme_manager
                theme_manager.remove_listener(self._theme_listener)
            except Exception:
                pass

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
                kill_coro = self._kill_all_tasks()
                try:
                    loop.create_task(kill_coro)
                except Exception:
                    # Coroutine was built before create_task could fail — close
                    # it so it never surfaces as a "never awaited" warning.
                    kill_coro.close()
                    raise
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

        try:
            from core.models_catalog import catalog

            if loop is not None and loop.is_running():
                # A fire-and-forget create_task() here races app shutdown: the
                # loop can close before the task ever runs, leaking the close
                # coroutine ("never awaited") and skipping the client close.
                # A short-lived daemon thread with its own loop always runs it.
                threading.Thread(
                    target=_close_catalog_sync, name="johnston-catalog-close", daemon=True
                ).start()
            else:
                # No running loop: run the close coroutine to completion in a
                # dedicated loop instead of leaving it un-awaited.
                try:
                    asyncio.run(catalog.close())
                except Exception:
                    pass
        except Exception as err:
            logger.debug(f"Catalog cleanup error: {err}")

        try:
            if loop is not None and loop.is_running():
                threading.Thread(
                    target=_close_tools_sync, name="johnston-tools-close", daemon=True
                ).start()
            else:
                _close_tools_sync()
        except Exception as err:
            logger.debug(f"Tool instance cleanup error: {err}")

        try:
            if hasattr(self, "sm") and hasattr(self.sm, "release_all_locks"):
                self.sm.release_all_locks()
        except Exception as err:
            logger.debug(f"Session lock cleanup error: {err}")

    async def _kill_all_tasks(self) -> None:
        try:
            await self.task_manager.kill_all()
        except Exception:
            pass

    def _kill_all_tasks_sync(self) -> None:
        for task in list(self.task_manager):
            try:
                kill_sync = getattr(task, "kill_sync", None)
                if callable(kill_sync) and not hasattr(task, "_mock_return_value"):
                    kill_sync()
                else:
                    kill = getattr(task, "kill", None)
                    if callable(kill) and asyncio.iscoroutinefunction(kill):
                        # Only schedule when a loop is actually running: creating
                        # the coroutine first (asyncio.create_task) and failing
                        # afterwards leaks it as a "never awaited" warning, and
                        # without a loop nothing could ever run it anyway.
                        try:
                            asyncio.get_running_loop().create_task(kill())
                        except RuntimeError:
                            pass
                    elif callable(kill):
                        kill()
                    elif callable(kill_sync):
                        kill_sync()
            except Exception:
                pass

    def refresh_status_footer(self) -> None:
        """Refresh status bar with directory, provider, model, context, tokens, cost, and subagents"""
        try:
            footer = self.query_one("#status-footer", StatusFooter)
            footer.refresh_footer()
        except Exception as e:
            logger.debug(f"Error refreshing status footer: {e}")
