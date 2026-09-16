"""App lifecycle service for Johnston TUI.

Encapsulates project switching, mount handling (theme registration, palette prewarming,
initial setup check, session lock conflict resolution), unmount cleanup (task killing,
worker cancellation, catalog and tools teardown), and status footer refresh.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
from typing import Any

from johnston.core import client as core_bridge
from johnston.tui.presentation.widgets.status_footer import StatusFooter

logger = logging.getLogger("johnston.app")


def _close_catalog_sync() -> None:
    """Run catalog.close() on a private loop (used from the shutdown thread)."""
    try:
        from johnston.core import client as core_bridge

        asyncio.run(core_bridge.catalog.close())
    except Exception as err:
        logger.debug(f"Catalog close error: {err}")


def _close_tools_sync() -> None:
    """Run aclose_tools() on a private loop (used from the shutdown thread)."""
    try:
        from johnston.core import client as core_bridge

        asyncio.run(core_bridge.aclose_tools())
    except Exception as err:
        logger.debug(f"Tool instance close error: {err}")


def _resolve_close_tools_sync():
    lifecycle_mod = sys.modules.get("johnston.tui.mixins.lifecycle")
    if lifecycle_mod and hasattr(lifecycle_mod, "_close_tools_sync"):
        return lifecycle_mod._close_tools_sync
    return _close_tools_sync


def _resolve_close_catalog_sync():
    lifecycle_mod = sys.modules.get("johnston.tui.mixins.lifecycle")
    if lifecycle_mod and hasattr(lifecycle_mod, "_close_catalog_sync"):
        return lifecycle_mod._close_catalog_sync
    return _close_catalog_sync


def _resolve_install_asyncio_exception_handler():
    lifecycle_mod = sys.modules.get("johnston.tui.mixins.lifecycle")
    if lifecycle_mod and hasattr(lifecycle_mod, "install_asyncio_exception_handler"):
        return lifecycle_mod.install_asyncio_exception_handler
    return core_bridge.install_asyncio_exception_handler


class AppLifecycleService:
    """App lifecycle service managing mount, unmount, project switching, and status refresh."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def refresh_status_footer(self) -> None:
        """Refresh status bar with directory, provider, model, context, tokens, cost, and subagents"""
        try:
            footer = self.app.query_one("#status-footer", StatusFooter)
            footer.refresh_footer()
        except Exception as e:
            logger.debug(f"Error refreshing status footer: {e}")

    def switch_project_dir(self, new_dir: str, branch: str = "") -> None:
        self.app.project_dir = new_dir
        try:
            os.chdir(new_dir)
        except Exception:
            pass
        from johnston.core import client as core_bridge

        core_bridge.get_permission_manager().get_instance().set_project_dir(new_dir)
        if getattr(self.app, "agent", None):
            self.app.agent.project_dir = new_dir
            self.app.agent.worktree_branch = branch
        if getattr(self.app, "session", None):
            self.app.session.project_dir = new_dir
            self.app.session.branch_name = branch
        if hasattr(self.app, "refresh_status_footer"):
            self.app.refresh_status_footer()
        else:
            self.refresh_status_footer()

    def handle_mount(self) -> None:
        """Instant focus on start, background catalog refresh and status bar refresh"""
        _resolve_install_asyncio_exception_handler()()
        from johnston.tui.app.theme_manager import prewarm_terminal_palette, theme_manager

        prewarm_terminal_palette()
        if hasattr(self.app, "register_theme"):
            available = getattr(self.app, "available_themes", {})
            for t in theme_manager.get_all_textual_themes():
                if t.name not in available:
                    self.app.register_theme(t)
            self.app.theme = theme_manager.current_theme.name
        self.app._theme_listener = (
            lambda _: self.app.refresh_status_footer()
            if hasattr(self.app, "refresh_status_footer")
            else self.refresh_status_footer()
        )
        theme_manager.add_listener(self.app._theme_listener)
        self.app.is_app_active = True
        try:
            from johnston.tui.presentation.widgets.chat_input import ChatInput

            self.app.query_one("#message-input", ChatInput).focus()
        except Exception:
            pass
        if getattr(self.app, "resume_session_id", None):
            res_id = self.app.resume_session_id
            if hasattr(self.app, "sm") and self.app.sm.is_session_locked(res_id) is True:
                from johnston.tui.presentation.screens.session_conflict import SessionConflictScreen

                def on_init_conflict(choice: str | None) -> None:
                    if choice == "steal":
                        self.app.sm.steal_session_lock(res_id)
                        self.app.load_session_ui(res_id)
                    elif choice == "readonly":
                        self.app.load_session_ui(res_id, read_only=True)
                    else:
                        new_id = self.app.sm.generate_session_id() if hasattr(self.app.sm, "generate_session_id") else ""
                        self.app.current_session_id = new_id
                        if hasattr(self.app.sm, "acquire_session_lock"):
                            self.app.sm.acquire_session_lock(new_id)
                        if hasattr(self.app.sm, "set_active_session_id"):
                            self.app.sm.set_active_session_id(new_id)
                        self.app.is_read_only = False
                        if hasattr(self.app, "notify"):
                            self.app.notify("Resume cancelled. Started new session.", severity="information")
                        if hasattr(self.app, "refresh_status_footer"):
                            self.app.refresh_status_footer()
                        else:
                            self.refresh_status_footer()

                self.app.push_screen(SessionConflictScreen(res_id), callback=on_init_conflict)
            else:
                self.app.load_session_ui(res_id)
        else:
            if getattr(self.app, "current_session_id", None) and hasattr(self.app, "sm"):
                if hasattr(self.app.sm, "acquire_session_lock"):
                    self.app.sm.acquire_session_lock(self.app.current_session_id)
            if getattr(self.app, "resume_session_id", None) == "":
                from johnston.tui.presentation.commands import ResumeCommand

                if hasattr(self.app, "create_tracked_task") and callable(self.app.create_tracked_task):
                    self.app.create_tracked_task(ResumeCommand().execute(self.app))
                else:
                    asyncio.create_task(ResumeCommand().execute(self.app))
        from johnston.core import client as core_bridge

        core_bridge.catalog.load_cache()
        if hasattr(self.app, "refresh_status_footer"):
            self.app.refresh_status_footer()
        else:
            self.refresh_status_footer()

        async def _refresh_catalog_bg() -> None:
            try:
                await core_bridge.catalog.refresh(force=False)
            except Exception:
                pass

        setup_check = (
            self.app._check_initial_setup()
            if hasattr(self.app, "_check_initial_setup")
            else self.check_initial_setup()
        )

        if hasattr(self.app, "create_tracked_task") and callable(self.app.create_tracked_task):
            self.app.create_tracked_task(core_bridge.get_mcp_manager().ensure_tools_ready_async())
            self.app.create_tracked_task(setup_check)
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                self.app.create_tracked_task(_refresh_catalog_bg())
        else:
            asyncio.create_task(core_bridge.get_mcp_manager().ensure_tools_ready_async())
            asyncio.create_task(setup_check)
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                asyncio.create_task(_refresh_catalog_bg())

        if getattr(self.app, "initial_prompt", None) and not getattr(self.app, "_initial_prompt_posted", False):
            self.app._initial_prompt_posted = True
            init_prompt = self.app.initial_prompt

            async def _post_initial_prompt() -> None:
                await asyncio.sleep(0.05)
                try:
                    from johnston.tui.presentation.widgets.chat_input import ChatInput

                    chat_input = self.app.query_one("#message-input", ChatInput)
                    chat_input.load_text("")
                    chat_input.add_to_history(init_prompt)
                    chat_input.post_message(ChatInput.Submitted(init_prompt))
                except Exception:
                    pass

            if hasattr(self.app, "create_tracked_task") and callable(self.app.create_tracked_task):
                self.app.create_tracked_task(_post_initial_prompt())
            else:
                asyncio.create_task(_post_initial_prompt())

    async def check_initial_setup(self) -> None:
        """Auto-prompt for provider/model selection on first launch if unconfigured"""
        if (
            getattr(self.app, "resume_session_id", None) is not None
            or getattr(self.app, "initial_prompt", None) is not None
            or os.environ.get("PYTEST_CURRENT_TEST")
            or not getattr(self.app, "is_app_active", True)
        ):
            return

        active_key = self.app.pm.get_active_provider_key()
        if not active_key or not self.app.pm.is_provider_connected(active_key):
            if not getattr(self.app, "is_app_active", True):
                return
            from johnston.tui.presentation.commands import ProvidersCommand

            await ProvidersCommand().execute(self.app)
        elif not getattr(getattr(self.app, "agent", None), "model", ""):
            from johnston.tui.presentation.commands import ModelsCommand

            await ModelsCommand().execute(self.app)

    def handle_unmount(self) -> None:
        """Clean up all running MCP servers and background processes when closing application"""
        self.app.is_app_active = False

        for w in getattr(self.app, "workers", []):
            if getattr(w, "is_running", False):
                w.cancel()

        if hasattr(self.app, "_theme_listener"):
            try:
                from johnston.tui.app.theme_manager import theme_manager

                theme_manager.remove_listener(self.app._theme_listener)
            except Exception:
                pass

        # Cancel an in-flight rewind git-restore task (kept on the agent by
        # rewind_session) so shutdown does not leave the worktree half-restored.
        git_task = getattr(getattr(self.app, "agent", None), "rewind_git_restore_task", None)
        if git_task is not None and not git_task.done():
            git_task.cancel()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        try:
            if loop is not None:
                kill_func = getattr(self.app, "_kill_all_tasks", self.kill_all_tasks)
                kill_coro = kill_func()
                try:
                    loop.create_task(kill_coro)
                except Exception:
                    # Coroutine was built before create_task could fail — close
                    # it so it never surfaces as a "never awaited" warning.
                    if hasattr(kill_coro, "close") and callable(kill_coro.close):
                        kill_coro.close()
                    raise
            else:
                kill_sync_func = getattr(self.app, "_kill_all_tasks_sync", self.kill_all_tasks_sync)
                kill_sync_func()
        except Exception as err:
            logger.debug(f"Background task cleanup error: {err}")
        try:
            from johnston.core import client as core_bridge

            core_bridge.cancel_running_subagents(self.app.sm)
        except Exception as err:
            logger.debug(f"Subagent cleanup error: {err}")

        try:
            self.app.save_current_session()
        except Exception as err:
            logger.debug(f"Unmount session save error: {err}")

        try:
            from johnston.core import client as core_bridge

            core_bridge.get_mcp_manager().stop_all()
        except Exception as err:
            logger.debug(f"MCP cleanup error: {err}")

        try:
            from johnston.core import client as core_bridge

            if loop is not None and loop.is_running():
                # A fire-and-forget create_task() here races app shutdown: the
                # loop can close before the task ever runs, leaking the close
                # coroutine ("never awaited") and skipping the client close.
                # A short-lived daemon thread with its own loop always runs it.
                close_cat_fn = _resolve_close_catalog_sync()
                threading.Thread(
                    target=close_cat_fn, name="johnston-catalog-close", daemon=True
                ).start()
            else:
                # No running loop: run the close coroutine to completion in a
                # dedicated loop instead of leaving it un-awaited.
                try:
                    from johnston.core import client as core_bridge

                    asyncio.run(core_bridge.catalog.close())
                except Exception:
                    pass
        except Exception as err:
            logger.debug(f"Catalog cleanup error: {err}")

        try:
            close_tools_fn = _resolve_close_tools_sync()
            if loop is not None and loop.is_running():
                threading.Thread(
                    target=close_tools_fn, name="johnston-tools-close", daemon=True
                ).start()
            else:
                close_tools_fn()
        except Exception as err:
            logger.debug(f"Tool instance cleanup error: {err}")

        try:
            if hasattr(self.app, "sm") and hasattr(self.app.sm, "release_all_locks"):
                self.app.sm.release_all_locks()
        except Exception as err:
            logger.debug(f"Session lock cleanup error: {err}")

    async def kill_all_tasks(self) -> None:
        try:
            await self.app.task_manager.kill_all()
        except Exception:
            pass

    def kill_all_tasks_sync(self) -> None:
        for task in list(getattr(self.app, "task_manager", [])):
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
