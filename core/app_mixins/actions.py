import asyncio

from textual import events
from textual.widgets import Select

from widgets.chat_input import ChatInput
from widgets.chat_view import ChatView, WelcomeWidget


class ActionsMixin:
    """Actions and pointer/selection event handlers for JohnstonApp."""

    def action_toggle_mode(self) -> None:
        """Toggle agent mode across all registered roles (builtin, global, project)"""
        if not hasattr(self, "agent") or not self.agent:
            return
        from core.role_registry import RoleRegistry

        roles_dict = RoleRegistry.get_instance().list_roles(scope="main_only")
        available_modes = list(roles_dict.keys())
        curr = getattr(self.agent, "mode", "act").lower()
        next_idx = (available_modes.index(curr) + 1) % len(available_modes) if curr in available_modes else 0
        new_mode = available_modes[next_idx]
        self.agent.mode = new_mode
        self.mode = new_mode
        self.refresh_status_footer()

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
        for t in list(getattr(self, "background_tasks", [])):
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
            banner_signatures = ["|_|", "\\__\\___/", "___ _| |_", "_  ___ |", "johnston"]
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
            sess = self.sm.load_session(self.current_session_id)
            history = sess.get("agent_history", []) if sess else None
            self.pm.recreate_active_agent(self, provider_key=event.value, history=history)
