from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict

from textual import events

from johnston.tui.presentation.widgets.chat_container import ChatView
from johnston.tui.presentation.widgets.chat_input import ChatInput
from johnston.tui.presentation.widgets.chat_welcome import WelcomeWidget
from johnston.tui.presentation.widgets.plan_notch import PlanActionsMixin

if TYPE_CHECKING:
    from johnston.tui.app.interaction_service import UserInteractionService


class ActionsMixin(PlanActionsMixin):
    """Actions and pointer/selection event handlers for JohnstonApp."""

    @classmethod
    def _resolve_interaction_service(cls, host: Any) -> UserInteractionService:
        service = getattr(host, "interaction_service", None)
        if service is None or getattr(service, "app", None) is not host:
            from johnston.tui.app.interaction_service import UserInteractionService

            service = UserInteractionService(host)
            try:
                host.interaction_service = service
            except Exception:
                pass
        return service

    def _get_interaction_service(self) -> UserInteractionService:
        """Get or lazily create UserInteractionService for this app."""
        return ActionsMixin._resolve_interaction_service(self)

    @property
    def interaction_service(self) -> UserInteractionService:
        """UserInteractionService managing confirmations, wizards, and backgrounding."""
        service = getattr(self, "_interaction_service", None)
        if service is None or getattr(service, "app", None) is not self:
            from johnston.tui.app.interaction_service import UserInteractionService

            service = UserInteractionService(self)
            self._interaction_service = service
        return service

    @interaction_service.setter
    def interaction_service(self, value: Any) -> None:
        self._interaction_service = value

    def action_toggle_role(self) -> None:
        """Toggle agent role across all registered roles (builtin, global, project)"""
        if not hasattr(self, "agent") or not self.agent:
            return
        from johnston.tui.app.role_service import toggle_agent_role

        toggle_agent_role(self)

    def action_toggle_mode(self) -> None:
        """Cycle execution mode: review -> edits -> yolo -> review"""
        from johnston.core import client as core_bridge

        core_bridge.cycle_execution_mode()
        if hasattr(self, "refresh_status_footer"):
            self.refresh_status_footer()



    def action_toggle_expand(self) -> None:
        """Toggle expand on all expandable widgets in chat"""
        try:
            chat_view = self.query_one(ChatView)
            chat_view.toggle_expand("all")
        except Exception:
            pass

    def action_background_all(self) -> None:
        """Background all running foreground shell tasks.

        Mirrors the session scoping used by the tasks screen:
        when a session is active, only its own tasks are affected. Tool cards are
        left as-is: an open expansion keeps streaming live output until the task
        completes and the completion callback repaints it.
        """
        ActionsMixin._resolve_interaction_service(self).background_all()

    def on_click(self, event: events.Click) -> None:
        """Any mouse click returns focus to input unless text is selected or interacting with focusable widgets"""
        from textual.screen import ModalScreen

        if isinstance(self.screen, ModalScreen):
            return
        target = getattr(event, "widget", None) or getattr(event, "target", None)
        if isinstance(target, ChatView):
            self.screen.clear_selection()
        try:
            chat_view = self.query_one(ChatView)
            if chat_view.query(WelcomeWidget):
                self.screen.clear_selection()
        except Exception:
            pass
        if self.screen.get_selected_text() or getattr(self, "selection_copy_active", False):
            return
        if target and getattr(target, "can_focus", False) and target is not self.query_one("#message-input"):
            return
        if target and ("button" in getattr(target, "classes", []) or "copy" in str(getattr(target, "id", ""))):
            return
        try:
            self.query_one("#message-input", ChatInput).focus()
        except Exception:
            pass

    def on_mouse_down(self, event: events.MouseDown) -> None:
        """Track mouse down position to distinguish clicks from text drag selection"""
        self._mouse_down_pos = (event.screen_x, event.screen_y)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        """On mouse up, copy selected fragment and clear selection"""
        down_pos = getattr(self, "_mouse_down_pos", None)
        self._mouse_down_pos = None

        try:
            chat_view = self.query_one(ChatView)
            if chat_view.query(WelcomeWidget):
                self.screen.clear_selection()
                return
        except Exception:
            pass

        target = getattr(event, "widget", None) or getattr(event, "target", None)
        curr = target
        while curr:
            if isinstance(curr, WelcomeWidget):
                self.screen.clear_selection()
                return
            curr = getattr(curr, "parent", None)

        is_drag = True
        if down_pos is not None:
            dx = abs(event.screen_x - down_pos[0])
            dy = abs(event.screen_y - down_pos[1])
            if dx == 0 and dy == 0:
                is_drag = False

        if not is_drag:
            self.screen.clear_selection()
            return

        selected_text = self.screen.get_selected_text()
        if not selected_text:
            try:
                ci = self.query_one("#message-input", ChatInput)
                if ci.selected_text:
                    selected_text = ci.selected_text
            except Exception:
                pass
        if selected_text and selected_text.strip():
            banner_signatures = ["|_|", "\\__\\___/", "___ _| |_", "_  ___ |"]
            if any(sig in selected_text for sig in banner_signatures):
                self.screen.clear_selection()
                return
            try:
                self.selection_copy_active = True
                self.copy_to_clipboard(selected_text)
            except Exception as e:
                self.notify(f"Copy failed: {e}", severity="error")
            finally:
                self.screen.clear_selection()

                async def reset_flag():
                    await asyncio.sleep(0.05)
                    self.selection_copy_active = False

                if hasattr(self, "create_tracked_task") and callable(self.create_tracked_task):
                    self.create_tracked_task(reset_flag())
                else:
                    asyncio.create_task(reset_flag())
        else:
            self.screen.clear_selection()

    async def confirm_permission(
        self,
        screen_name: str,
        args: Dict[str, Any],
        reason: str = "",
        perm_name: str | None = None,
        is_subagent: bool = False,
        subagent_role: str = "",
        server_name: str | None = None,
        *call_args: Any,
        **kwargs: Any,
    ) -> bool | str:
        """Shows the permission confirmation screen and applies session overrides for confirmed tools.

        Returns True if the user granted access ('allow' or 'always_allow'), False otherwise.
        This is the UI-side implementation of tool permission prompting, owned by the app
        layer so that the tools layer stays independent of Textual widgets.
        """
        return await ActionsMixin._resolve_interaction_service(self).confirm_permission(
            screen_name,
            args,
            reason=reason,
            perm_name=perm_name,
            is_subagent=is_subagent,
            subagent_role=subagent_role,
            server_name=server_name,
            *call_args,
            **kwargs,
        )

    async def ask_user(self, questions: list[Dict[str, Any]]) -> str:
        """Shows the AskUserWizardScreen and returns the user's answer.

        Owned by the app layer so the tools layer stays independent of Textual widgets.
        Returns the selected answer string, or "cancelled by user" on cancel/error.
        """
        return await ActionsMixin._resolve_interaction_service(self).ask_user(questions)
