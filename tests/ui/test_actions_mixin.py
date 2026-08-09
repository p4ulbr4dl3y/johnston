"""Coverage-focused tests for core/app_mixins/actions.py.

These tests exercise the uncovered branches of ActionsMixin (pointer handlers,
mode toggling, expand/background actions, provider switching) using a mounted
real JohnstonApp where possible, matching the style in tests/ui/test_app.py.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app import JohnstonApp
from core.app_mixins.actions import ActionsMixin


def _bare_mixin() -> ActionsMixin:
    """Return an ActionsMixin instance with no App backing (for early-return branches)."""
    obj = ActionsMixin.__new__(ActionsMixin)
    return obj


class TestActionsMode(unittest.IsolatedAsyncioTestCase):
    async def test_action_toggle_mode_cycles(self):
        app = JohnstonApp()
        async with app.run_test():
            self.assertEqual(app.agent.mode, "act")
            app.action_toggle_mode()
            self.assertNotEqual(app.agent.mode, "act")

    async def test_action_toggle_mode_no_agent(self):
        obj = _bare_mixin()
        # No `agent` attribute -> early return
        obj.action_toggle_mode()

    async def test_action_toggle_expand(self):
        app = JohnstonApp()
        async with app.run_test():
            with patch.object(app, "query_one", return_value=MagicMock()) as mock_q:
                app.action_toggle_expand()
                mock_q.assert_called_once()
                mock_q.return_value.toggle_expand.assert_called_once_with("all")

    async def test_action_toggle_expand_exception(self):
        app = JohnstonApp()
        async with app.run_test():
            with patch.object(app, "query_one", side_effect=Exception("boom")):
                app.action_toggle_expand()  # must not raise

    async def test_action_background_all_empty(self):
        app = JohnstonApp()
        async with app.run_test():
            app.background_tasks = []
            app.notify = MagicMock()
            app.action_background_all()
            app.notify.assert_called_once()
            self.assertIn("No active foreground", app.notify.call_args.args[0])

    async def test_action_background_all_moves_task(self):
        app = JohnstonApp()
        async with app.run_test():
            task = MagicMock()
            task.is_running = True
            task.is_background = False
            task.move_to_background = MagicMock()
            app.background_tasks = [task]
            app.action_background_all()
            task.move_to_background.assert_called_once()

    async def test_action_background_all_no_move_method(self):
        app = JohnstonApp()
        async with app.run_test():
            task = MagicMock()
            task.is_running = True
            task.is_background = False
            del task.move_to_background
            app.background_tasks = [task]
            app.action_background_all()
            self.assertTrue(task.is_background)


class TestActionsPointer(unittest.IsolatedAsyncioTestCase):
    async def test_on_click_focuses_input(self):
        from textual import events

        app = JohnstonApp()
        async with app.run_test():
            app.selection_copy_active = False
            app.screen.get_selected_text = MagicMock(return_value="")
            app.screen.clear_selection = MagicMock()
            click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
            target = MagicMock()
            target.can_focus = False
            target.classes = []
            target.id = "other"
            click_evt.widget = target
            app.on_click(click_evt)
            app.screen.clear_selection.assert_called()

    async def test_on_click_selected_text_returns(self):
        from textual import events

        app = JohnstonApp()
        async with app.run_test():
            app.selection_copy_active = False
            app.screen.get_selected_text = MagicMock(return_value="selected")
            click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
            click_evt.widget = None
            app.on_click(click_evt)

    async def test_on_click_focusable_target_returns(self):
        from textual import events

        app = JohnstonApp()
        async with app.run_test():
            app.screen.get_selected_text = MagicMock(return_value="")
            click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
            target = MagicMock()
            target.can_focus = True
            target.classes = []
            target.id = "not-input"
            click_evt.widget = target
            with patch.object(app, "query_one", return_value=MagicMock()) as mock_q:
                app.on_click(click_evt)
                mock_q.return_value.focus.assert_not_called()

    async def test_on_click_button_target_returns(self):
        from textual import events

        app = JohnstonApp()
        async with app.run_test():
            app.screen.get_selected_text = MagicMock(return_value="")
            click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
            target = MagicMock()
            target.can_focus = True
            target.classes = ["button"]
            target.id = "x"
            click_evt.widget = target
            app.on_click(click_evt)

    async def test_on_click_copy_id_target_returns(self):
        from textual import events

        app = JohnstonApp()
        async with app.run_test():
            app.screen.get_selected_text = MagicMock(return_value="")
            click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
            target = MagicMock()
            target.can_focus = False
            target.classes = []
            target.id = "copy-btn"
            click_evt.widget = target
            app.on_click(click_evt)

    async def test_on_click_chatview_target_clears_selection(self):
        from textual import events

        from widgets.chat_view import ChatView

        app = JohnstonApp()
        async with app.run_test():
            app.screen.get_selected_text = MagicMock(return_value="")
            app.screen.clear_selection = MagicMock()
            click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
            click_evt.widget = ChatView()
            app.on_click(click_evt)
            app.screen.clear_selection.assert_called()

    async def test_on_click_modal_screen_returns(self):
        from textual import events
        from textual.screen import ModalScreen

        obj = MagicMock()
        obj.screen.__class__ = ModalScreen
        click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
        ActionsMixin.on_click(obj, click_evt)
        obj.screen.clear_selection.assert_not_called()

    async def test_on_click_query_exception(self):
        from textual import events

        app = JohnstonApp()
        async with app.run_test():
            app.screen.get_selected_text = MagicMock(return_value="")
            with patch.object(app, "query_one", side_effect=Exception("no chat view")):
                click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
                click_evt.widget = None
                app.on_click(click_evt)

    def test_on_mouse_down_tracks_position(self):
        app = MagicMock()
        event = MagicMock()
        event.screen_x = 10
        event.screen_y = 20
        ActionsMixin.on_mouse_down(app, event)
        self.assertEqual(app._mouse_down_pos, (10, 20))


class TestActionsMouseUp(unittest.IsolatedAsyncioTestCase):
    async def _make_app(self):
        app = JohnstonApp()
        async with app.run_test():
            yield app

    async def test_on_mouse_up_no_down_pos(self):

        app = JohnstonApp()
        async with app.run_test():
            app.selection_copy_active = False
            app.screen.get_selected_text = MagicMock(return_value="")
            app.screen.clear_selection = MagicMock()
            app._mouse_down_pos = None
            event = MagicMock()
            event.screen_x = 5
            event.screen_y = 5
            app.on_mouse_up(event)
            app.screen.clear_selection.assert_called()

    async def test_on_mouse_up_welcome_clear(self):

        app = JohnstonApp()
        async with app.run_test():
            app.screen.clear_selection = MagicMock()
            app._mouse_down_pos = (0, 0)
            event = MagicMock()
            event.screen_x = 0
            event.screen_y = 0
            with patch.object(app, "query_one", return_value=MagicMock()):
                app.on_mouse_up(event)
            app.screen.clear_selection.assert_called()

    async def test_on_mouse_up_query_one_exception(self):
        app = JohnstonApp()
        async with app.run_test():
            app.selection_copy_active = False
            app.screen.get_selected_text = MagicMock(return_value="")
            app.screen.clear_selection = MagicMock()
            app._mouse_down_pos = None
            with patch.object(app, "query_one", side_effect=Exception("boom")):
                event = MagicMock()
                event.screen_x = 5
                event.screen_y = 5
                event.widget = None
                event.target = None
                app.on_mouse_up(event)
            app.screen.clear_selection.assert_called()

    async def test_on_mouse_up_drag_copy(self):
        import asyncio

        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (0, 0)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="hello world")
            app.copy_to_clipboard = MagicMock()
            chat_view = MagicMock()
            chat_view.query.return_value = []
            with patch.object(app, "query_one", return_value=chat_view):
                event = MagicMock()
                event.screen_x = 10
                event.screen_y = 10
                event.widget = None
                event.target = None
                app.on_mouse_up(event)
            app.copy_to_clipboard.assert_called_once_with("hello world")
            self.assertTrue(app.selection_copy_active)
            await asyncio.sleep(0.1)
            self.assertFalse(app.selection_copy_active)

    async def test_on_mouse_up_banner_text(self):
        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (0, 0)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="__ johnston |_|")
            app.copy_to_clipboard = MagicMock()
            chat_view = MagicMock()
            chat_view.query.return_value = []
            with patch.object(app, "query_one", return_value=chat_view):
                event = MagicMock()
                event.screen_x = 10
                event.screen_y = 10
                event.widget = None
                event.target = None
                app.on_mouse_up(event)
            app.copy_to_clipboard.assert_not_called()

    async def test_on_mouse_up_non_drag_clears(self):
        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (0, 0)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="")
            chat_view = MagicMock()
            chat_view.query.return_value = []
            with patch.object(app, "query_one", return_value=chat_view):
                event = MagicMock()
                event.screen_x = 0
                event.screen_y = 0
                event.widget = None
                event.target = None
                app.on_mouse_up(event)
            app.screen.clear_selection.assert_called()

    async def test_on_mouse_up_selected_text_else_clears(self):
        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (0, 0)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="   ")
            app.copy_to_clipboard = MagicMock()
            chat_view = MagicMock()
            chat_view.query.return_value = []
            with patch.object(app, "query_one", return_value=chat_view):
                event = MagicMock()
                event.screen_x = 10
                event.screen_y = 10
                event.widget = None
                event.target = None
                app.on_mouse_up(event)
            app.copy_to_clipboard.assert_not_called()

    async def test_on_mouse_up_target_is_chatview(self):
        from widgets.chat_view import ChatView

        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (0, 0)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="selected chat text")
            app.copy_to_clipboard = MagicMock()
            chat_view = MagicMock()
            chat_view.query.return_value = []
            with patch.object(app, "query_one", return_value=chat_view):
                event = MagicMock()
                event.screen_x = 10
                event.screen_y = 10
                event.widget = ChatView()
                event.target = None
                app.on_mouse_up(event)
            app.copy_to_clipboard.assert_called_once_with("selected chat text")

    async def test_on_mouse_up_welcome_query_clear(self):
        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (0, 0)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="")
            chat_view = MagicMock()
            chat_view.query.return_value = [MagicMock()]
            with patch.object(app, "query_one", return_value=chat_view):
                event = MagicMock()
                event.screen_x = 10
                event.screen_y = 10
                event.widget = None
                event.target = None
                app.on_mouse_up(event)
            app.screen.clear_selection.assert_called()

    async def test_on_mouse_up_welcome_widget_parent(self):
        from widgets.chat_view import WelcomeWidget

        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (0, 0)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="")
            chat_view = MagicMock()
            chat_view.query.return_value = []
            with patch.object(app, "query_one", return_value=chat_view):
                event = MagicMock()
                event.screen_x = 10
                event.screen_y = 10
                event.widget = MagicMock()
                event.target = None
                event.widget.parent = WelcomeWidget()
                app.on_mouse_up(event)
            app.screen.clear_selection.assert_called()

    async def test_on_mouse_up_copy_failure(self):
        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (0, 0)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="hello")
            app.copy_to_clipboard = MagicMock(side_effect=Exception("no clipboard"))
            app.notify = MagicMock()
            chat_view = MagicMock()
            chat_view.query.return_value = []
            with patch.object(app, "query_one", return_value=chat_view):
                event = MagicMock()
                event.screen_x = 10
                event.screen_y = 10
                event.widget = None
                event.target = None
                app.on_mouse_up(event)
            app.notify.assert_called_once()
            self.assertIn("Copy failed", app.notify.call_args.args[0])


class TestActionsSelectChanged(unittest.TestCase):
    def test_on_select_changed(self):
        obj = MagicMock()
        obj.mode = "act"
        obj.pm = MagicMock()
        obj.agent = MagicMock(mode="act", history=[])
        obj.sm = MagicMock()
        obj.sm.get.return_value = MagicMock(agent_history=[{"role": "user", "content": "hi"}])
        obj.current_session_id = "sess1"
        event = MagicMock()
        event.value = "openai"
        ActionsMixin.on_select_changed(obj, event)
        obj.pm.recreate_active_agent.assert_called_once_with(
            obj, provider_key="openai", history=[{"role": "user", "content": "hi"}]
        )

    def test_on_select_changed_none_value(self):
        obj = MagicMock()
        obj.mode = "act"
        obj.pm = MagicMock()
        obj.agent = MagicMock()
        event = MagicMock()
        event.value = "none"
        ActionsMixin.on_select_changed(obj, event)
        obj.pm.set_active_provider_key.assert_not_called()

    def test_on_select_changed_no_history(self):
        obj = MagicMock()
        obj.mode = "act"
        obj.pm = MagicMock()
        obj.agent = MagicMock(mode="act")
        del obj.agent.history
        obj.sm = MagicMock()
        obj.sm.get.return_value = None
        obj.current_session_id = "sess1"
        event = MagicMock()
        event.value = "anthropic"
        ActionsMixin.on_select_changed(obj, event)
        obj.pm.recreate_active_agent.assert_called_once_with(obj, provider_key="anthropic", history=None)


class TestActionsConfirmPermission(unittest.IsolatedAsyncioTestCase):
    async def test_confirm_permission_always_allow_sets_overrides(self):
        from core.permission_manager import PermissionManager

        pm = PermissionManager.get_instance()
        pm.clear_session_overrides()

        app = JohnstonApp()
        async with app.run_test():
            with (
                patch.object(app, "push_screen_wait", new=AsyncMock(return_value="always_allow")),
                patch("core.permission_manager.PermissionManager.get_instance", return_value=pm),
            ):
                result = await app.confirm_permission("shell", {"command": "ls"}, "Destructive", "shell")
            self.assertTrue(result)
            self.assertEqual(pm.session_overrides.get("shell"), "allow")
            self.assertEqual(pm.session_overrides.get("shell_guard"), "allow")
            pm.clear_session_overrides()

    async def test_confirm_permission_denied(self):
        from core.permission_manager import PermissionManager

        pm = PermissionManager.get_instance()
        pm.clear_session_overrides()

        app = JohnstonApp()
        async with app.run_test():
            with patch.object(app, "push_screen_wait", new=AsyncMock(return_value="no")):
                result = await app.confirm_permission("read", {"path": "x"}, "Confirm")
            self.assertFalse(result)

    async def test_confirm_permission_callable_fallback(self):
        app = JohnstonApp()
        async with app.run_test():
            with patch.object(app, "push_screen", new=MagicMock()) as mock_ps:

                async def resolve():
                    pass

                app.push_screen_wait = AsyncMock(side_effect=TypeError("no wait"))

                # push_screen callback path: invoke callback with "allow"
                def on_dismiss(screen, callback):
                    callback("allow")

                mock_ps.side_effect = on_dismiss
                result = await app.confirm_permission("read", {"path": "x"}, "Confirm")
            self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
