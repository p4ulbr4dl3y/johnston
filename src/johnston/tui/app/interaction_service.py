"""User interaction service for Johnston TUI.

Manages user confirmations, interactive wizards, and task backgrounding.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class UserInteractionService:
    """Service managing interactive dialogs, permissions, and wizard flows."""

    def __init__(self, app: Any) -> None:
        self.app = app

    @property
    def pending_ask_user(self) -> Any:
        """Get the pending ask_user resume callback if minimized."""
        return getattr(self.app, "_pending_ask_user", None)

    @pending_ask_user.setter
    def pending_ask_user(self, val: Any) -> None:
        setattr(self.app, "_pending_ask_user", val)

    async def confirm_permission(
        self,
        screen_name: str,
        args: dict[str, Any],
        reason: str = "",
        perm_name: str | None = None,
        is_subagent: bool = False,
        subagent_role: str = "",
        server_name: str | None = None,
        *call_args: Any,
        **kwargs: Any,
    ) -> bool | str:
        """Show permission confirmation screen and apply session overrides for confirmed tools.

        Returns True if the user granted access ('allow' or 'always_allow'), False otherwise.
        This is the UI-side implementation of tool permission prompting, owned by the app
        layer so that the tools layer stays independent of Textual widgets.
        """
        from johnston.tui.adapters import core_bridge
        from johnston.tui.presentation.screens.permission_confirm import PermissionConfirmScreen

        screen = PermissionConfirmScreen(
            tool_name=screen_name,
            args=args,
            is_subagent=is_subagent,
            subagent_role=subagent_role,
            server_name=server_name,
        )

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()

        def on_dismiss(r: Any) -> None:
            if not future.done():
                future.set_result(r)

        self.app.push_screen(screen, callback=on_dismiss)
        result = await future

        return core_bridge.apply_permission_choice(result, perm_name)

    async def ask_user(self, questions: list[dict[str, Any]]) -> str:
        """Show the AskUserWizardScreen and return the user's answer.

        Owned by the app layer so the tools layer stays independent of Textual widgets.
        Returns the selected answer string, or 'cancelled by user' on cancel/error.
        """
        from johnston.tui.presentation.screens.ask_user import AskUserWizardScreen

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        active_screen: Any = None

        def _show_wizard(
            question_list: list[dict[str, Any]],
            answers: dict[str, Any] | None = None,
            q_idx: int = 0,
        ) -> None:
            nonlocal active_screen
            active_screen = AskUserWizardScreen(question_list, answers=answers, q_idx=q_idx)

            def on_dismiss(result: Any) -> None:
                if isinstance(result, dict) and result.get("action") == "minimize":
                    saved_answers = result.get("answers", {})
                    saved_q_idx = result.get("q_idx", 0)
                    setattr(
                        self.app,
                        "_pending_ask_user",
                        lambda: _show_wizard(question_list, saved_answers, saved_q_idx),
                    )
                    if hasattr(self.app, "notify"):
                        try:
                            self.app.notify("Questions minimized: type /questions to resume", severity="information")
                        except Exception:
                            pass
                else:
                    if hasattr(self.app, "_pending_ask_user"):
                        setattr(self.app, "_pending_ask_user", None)
                    if not future.done():
                        future.set_result(result)

            self.app.push_screen(active_screen, callback=on_dismiss)

        _show_wizard(questions)

        try:
            res = await future
        finally:
            if hasattr(self.app, "_pending_ask_user") and future.done():
                setattr(self.app, "_pending_ask_user", None)
            if not future.done():
                future.cancel()
                if active_screen is not None:
                    try:
                        active_screen.dismiss(None)
                    except Exception:
                        pass

        if isinstance(res, str) and res.strip() and res != "cancelled":
            return res
        return "cancelled by user"

    def background_all(self) -> None:
        """Background all running foreground shell tasks scoped to current session.

        Mirrors the session scoping used by the tasks screen:
        when a session is active, only its own tasks are affected. Tool cards are
        left as-is: an open expansion keeps streaming live output until the task
        completes and the completion callback repaints it.
        """
        from johnston.tui.adapters import core_bridge

        count = 0
        task_manager = getattr(self.app, "task_manager", []) or []
        shell_tasks = [t for t in task_manager if getattr(t, "kind", "") == "shell"]
        fg_tasks = list(getattr(self.app, "_foreground_shell_tasks", {}).values())
        all_tasks = core_bridge.filter_to_session(shell_tasks + fg_tasks, getattr(self.app, "current_session_id", None))
        for t in list(all_tasks):
            if getattr(t, "is_active", getattr(t, "is_running", False)) and not getattr(t, "is_background", False):
                if hasattr(t, "move_to_background"):
                    t.move_to_background()
                    count += 1
                else:
                    t.is_background = True
                    count += 1
        if count == 0 and hasattr(self.app, "notify"):
            self.app.notify("No active foreground tasks to move to background", severity="warning")

    action_background_all = background_all
