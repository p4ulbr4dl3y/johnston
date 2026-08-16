import asyncio
from typing import Any, Dict

from textual import events
from textual.widgets import Select

from widgets.chat_input import ChatInput
from widgets.presentation.widgets.chat_container import ChatView
from widgets.presentation.widgets.chat_welcome import WelcomeWidget


class ActionsMixin:
    """Actions and pointer/selection event handlers for JohnstonApp."""

    def action_toggle_role(self) -> None:
        """Toggle agent role across all registered roles (builtin, global, project)"""
        if not hasattr(self, "agent") or not self.agent:
            return
        from widgets.app.role_service import toggle_agent_role

        toggle_agent_role(self)

    def action_toggle_expand(self) -> None:
        """Toggle expand on all expandable widgets in chat"""
        try:
            chat_view = self.query_one(ChatView)
            chat_view.toggle_expand("all")
        except Exception:
            pass

    def action_background_all(self) -> None:
        """Background all running foreground shell tasks"""
        count = 0
        shell_tasks = [t for t in self.task_manager if getattr(t, "kind", "") == "shell"]
        for t in list(shell_tasks):
            if getattr(t, "is_running", False) and not getattr(t, "is_background", False):
                if hasattr(t, "move_to_background"):
                    t.move_to_background()
                    count += 1
                else:
                    t.is_background = True
                    count += 1
        if count == 0:
            self.notify("No active foreground tasks to move to background", severity="warning")

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

        selected_text = self.screen.get_selected_text()
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

                asyncio.create_task(reset_flag())
        else:
            self.screen.clear_selection()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Switch agent provider from ~/.johnston config"""
        if event.value and isinstance(event.value, str) and event.value != "none":
            sess = self.sm.get(self.current_session_id)
            history = sess.agent_history if sess else None
            self.pm.recreate_active_agent(self, provider_key=event.value, history=history)

    async def confirm_permission(
        self, screen_name: str, args: Dict[str, Any], reason: str, perm_name: str | None = None
    ) -> bool:
        """Shows the permission confirmation screen and applies session overrides for confirmed tools.

        Returns True if the user granted access ('allow' or 'always_allow'), False otherwise.
        This is the UI-side implementation of tool permission prompting, owned by the app
        layer so that the tools layer stays independent of Textual widgets.
        """
        from core.permission_manager import PermissionManager
        from widgets.screens.permission_confirm import PermissionConfirmScreen

        pm = PermissionManager.get_instance()
        screen = PermissionConfirmScreen(tool_name=screen_name, args=args, reason=reason)

        result = None
        if hasattr(self, "push_screen_wait"):
            try:
                result = await self.push_screen_wait(screen)
            except TypeError:
                result = None

        if result is None:
            loop = asyncio.get_running_loop()
            future = loop.create_future()

            def on_dismiss(r: Any) -> None:
                if not future.done():
                    future.set_result(r)

            self.push_screen(screen, callback=on_dismiss)
            result = await future

        if result == "always_allow":
            if perm_name:
                pm.set_session_override(perm_name, "allow")
        return result in ("allow", "always_allow")

    async def ask_user(self, questions: list[Dict[str, Any]]) -> str:
        """Shows the AskUserWizardScreen and returns the user's answer.

        Owned by the app layer so the tools layer stays independent of Textual widgets.
        Returns the selected answer string, or "cancelled by user" on cancel/error.
        """
        from widgets.screens.ask_user import AskUserWizardScreen

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def _show_wizard(question_list, answers=None, q_idx=0):
            screen = AskUserWizardScreen(question_list, answers=answers, q_idx=q_idx)

            def on_dismiss(result):
                if isinstance(result, dict) and result.get("action") == "minimize":
                    saved_answers = result.get("answers", {})
                    saved_q_idx = result.get("q_idx", 0)
                    setattr(
                        self,
                        "_pending_ask_user",
                        lambda: _show_wizard(question_list, saved_answers, saved_q_idx),
                    )
                    if hasattr(self, "notify"):
                        try:
                            self.notify("Questions minimized: type /questions to resume", severity="info")
                        except Exception:
                            pass
                else:
                    if hasattr(self, "_pending_ask_user"):
                        setattr(self, "_pending_ask_user", None)
                    if not future.done():
                        future.set_result(result)

            self.push_screen(screen, callback=on_dismiss)

        _show_wizard(questions)

        try:
            res = await future
        finally:
            if hasattr(self, "_pending_ask_user") and future.done():
                setattr(self, "_pending_ask_user", None)

        if isinstance(res, str) and res.strip() and res != "cancelled":
            return res
        return "cancelled by user"
